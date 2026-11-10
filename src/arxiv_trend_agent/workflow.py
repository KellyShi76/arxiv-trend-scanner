from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from .agents import PaperAnalystAgent, QueryPlannerAgent, TrendAnalystAgent
from .arxiv_client import ArxivClient, merge_versions
from .models import (
    AgentEvent,
    PDFDocument,
    Paper,
    SearchPlan,
    ThemeDefinition,
    WorkflowConfig,
    WorkflowResult,
)
from .pdf_parser import PDFParser
from .reporting import write_outputs
from .trend import calculate_trends


class TrendWorkflow:
    def __init__(
        self,
        client: ArxivClient,
        backend: Any | None = None,
        *,
        pdf_parser: PDFParser | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> None:
        self.client = client
        self.pdf_parser = pdf_parser
        self.progress = progress or (lambda percent, message: None)
        self.query_agent = QueryPlannerAgent(backend)
        self.paper_agent = PaperAnalystAgent(backend)
        self.trend_agent = TrendAnalystAgent(backend)

    def run(self, config: WorkflowConfig) -> tuple[WorkflowResult, dict[str, object]]:
        self.progress(3, "Planning a reproducible arXiv search")
        plan = self.query_agent.run(config.topic, config.explicit_queries)
        all_papers: list[Paper] = []
        executed: list[dict[str, object]] = []
        warnings: list[str] = []

        recent_start = config.as_of - timedelta(days=config.recent_days)
        baseline_start = recent_start - timedelta(days=config.baseline_days)
        baseline_end = recent_start - timedelta(days=1)

        def execute(base_query: str, period: str, start: date, end: date) -> None:
            self.progress(
                10 + len(executed) * 8,
                f"Retrieving {period.replace('-', ' ')} arXiv records",
            )
            query = _with_date_filter(base_query, start, end)
            response = self.client.search(
                query,
                max_results=config.max_results,
                refresh=config.refresh_cache,
            )
            all_papers.extend(response.papers)
            in_scope = _in_date_range(
                merge_versions(all_papers),
                config=config,
            )
            executed.append(
                {
                    "period": period,
                    "base_query": base_query,
                    "query": query,
                    "request_url": response.request_url,
                    "returned_records": len(response.papers),
                    "total_results_reported_by_arxiv": response.total_results,
                    "unique_in_window_after_merge": len(in_scope),
                    "from_cache": response.from_cache,
                }
            )

        execute(plan.queries[0], "recent", recent_start, config.as_of)
        execute(plan.queries[0], "baseline", baseline_start, baseline_end)
        scoped = _in_date_range(merge_versions(all_papers), config=config)
        if len(scoped) < config.min_candidates and len(plan.queries) > 1:
            execute(plan.queries[1], "recent-fallback", recent_start, config.as_of)
            execute(plan.queries[1], "baseline-fallback", baseline_start, baseline_end)
            scoped = _in_date_range(merge_versions(all_papers), config=config)

        pdf_documents: list[PDFDocument] = []
        pdf_events: list[AgentEvent] = []
        if config.parse_pdfs:
            if self.pdf_parser is None:
                warnings.append("PDF parsing was requested but no PDF parser was configured.")
            else:
                self.progress(38, "Screening records before bounded PDF retrieval")
                candidates = _select_pdf_candidates(
                    scoped,
                    topic=config.topic,
                    plan=plan,
                    themes=config.themes,
                    as_of=config.as_of,
                    recent_days=config.recent_days,
                    limit=config.max_pdfs,
                )
                for index, paper in enumerate(candidates, start=1):
                    progress = 40 + int(25 * index / max(1, len(candidates)))
                    self.progress(
                        progress,
                        f"Parsing PDF {index}/{len(candidates)}: {paper.arxiv_id}",
                    )
                    pdf_documents.append(
                        self.pdf_parser.parse_paper(
                            paper,
                            refresh=config.refresh_cache,
                        )
                    )
                parsed_count = sum(item.status == "parsed" for item in pdf_documents)
                failed_count = sum(item.status != "parsed" for item in pdf_documents)
                pdf_events.append(
                    AgentEvent(
                        "PDF Parser",
                        "local-pymupdf",
                        f"Parsed {parsed_count} PDF(s); {failed_count} failed or were skipped.",
                    )
                )
                if failed_count:
                    warnings.append(
                        f"{failed_count} selected PDF(s) could not be parsed; those records used "
                        "abstract-only analysis."
                    )

        self.progress(68, "Analyzing the retrieved evidence")
        pdf_by_id = {
            document.arxiv_id: document
            for document in pdf_documents
            if document.status == "parsed"
        }
        analyses = [
            self.paper_agent.run(
                config.topic,
                paper,
                plan,
                config.themes,
                full_text=pdf_by_id[paper.arxiv_id].analysis_text
                if paper.arxiv_id in pdf_by_id
                else "",
                evidence_sections=pdf_by_id[paper.arxiv_id].sections
                if paper.arxiv_id in pdf_by_id
                else (),
            )
            for paper in scoped
        ]
        self.paper_agent.finish(len(analyses), full_text_count=len(pdf_by_id))
        self.progress(84, "Calculating recent-versus-baseline theme signals")
        trends = calculate_trends(
            scoped,
            analyses,
            config.themes,
            as_of=config.as_of,
            recent_days=config.recent_days,
            baseline_days=config.baseline_days,
        )
        insights = self.trend_agent.run(config.topic, trends)
        final_relevant = sum(analysis.relevant for analysis in analyses)
        if final_relevant < config.min_relevant:
            warnings.append(
                f"Only {final_relevant} relevant records were found; trend signals are sparse."
            )
        if not insights:
            warnings.append("No trend observation had at least two supporting papers.")

        result = WorkflowResult(
            plan=plan,
            papers=scoped,
            analyses=analyses,
            trends=trends,
            insights=insights,
            executed_queries=executed,
            pdf_documents=pdf_documents,
            warnings=warnings,
            agent_trace=(
                self.query_agent.events
                + pdf_events
                + self.paper_agent.events
                + self.trend_agent.events
            ),
        )
        self.progress(94, "Writing the report and evidence files")
        paths = write_outputs(config, result)
        self.progress(100, "Run complete")
        return result, paths


def _in_date_range(papers: list[Paper], *, config: WorkflowConfig) -> list[Paper]:
    start = config.as_of - timedelta(days=config.recent_days + config.baseline_days)
    return [
        paper
        for paper in papers
        if start <= paper.published.date() <= config.as_of
    ]


def _with_date_filter(query: str, start: date, end: date) -> str:
    start_value = start.strftime("%Y%m%d") + "0000"
    end_value = end.strftime("%Y%m%d") + "2359"
    return f"({query}) AND submittedDate:[{start_value} TO {end_value}]"


def _select_pdf_candidates(
    papers: list[Paper],
    *,
    topic: str,
    plan: SearchPlan,
    themes: tuple[ThemeDefinition, ...],
    as_of: date,
    recent_days: int,
    limit: int,
) -> list[Paper]:
    """Select relevant PDFs with balanced coverage across both trend windows."""
    screener = PaperAnalystAgent()
    relevant = [
        paper
        for paper in papers
        if screener.run(topic, paper, plan, themes).relevant
    ]
    recent_start = as_of - timedelta(days=recent_days)
    recent = [paper for paper in relevant if paper.published.date() >= recent_start]
    baseline = [paper for paper in relevant if paper.published.date() < recent_start]
    selected: list[Paper] = []
    while len(selected) < limit and (recent or baseline):
        if recent and len(selected) < limit:
            selected.append(recent.pop(0))
        if baseline and len(selected) < limit:
            selected.append(baseline.pop(0))
    return selected

