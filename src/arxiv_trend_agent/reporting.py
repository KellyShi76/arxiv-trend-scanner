from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agents import method_counts
from .models import WorkflowConfig, WorkflowResult, json_ready
from .pdf_parser import pdf_metadata
from .trend import period_counts


def write_outputs(config: WorkflowConfig, result: WorkflowResult) -> dict[str, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": config.output_dir / "trend_report.md",
        "papers_json": config.output_dir / "papers.json",
        "papers_csv": config.output_dir / "papers.csv",
        "pdf_extraction": config.output_dir / "pdf_extraction.json",
        "manifest": config.output_dir / "run_manifest.json",
    }

    analysis_by_id = {analysis.arxiv_id: analysis for analysis in result.analyses}
    paper_records = []
    for paper in result.papers:
        record = json_ready(paper)
        record["analysis"] = json_ready(analysis_by_id[paper.arxiv_id])
        record["source_scope"] = analysis_by_id[paper.arxiv_id].source_scope
        paper_records.append(record)
    paths["papers_json"].write_text(
        json.dumps(paper_records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pdf_records = [pdf_metadata(document) for document in result.pdf_documents]
    paths["pdf_extraction"].write_text(
        json.dumps(pdf_records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with paths["papers_csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "arxiv_id",
                "title",
                "published",
                "authors",
                "categories",
                "relevant",
                "relevance_score",
                "themes",
                "methods",
                "source_scope",
                "url",
            ],
        )
        writer.writeheader()
        for paper in result.papers:
            analysis = analysis_by_id[paper.arxiv_id]
            writer.writerow(
                {
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "published": paper.published.date().isoformat(),
                    "authors": "; ".join(paper.authors),
                    "categories": "; ".join(paper.categories),
                    "relevant": analysis.relevant,
                    "relevance_score": analysis.relevance_score,
                    "themes": "; ".join(analysis.themes),
                    "methods": "; ".join(analysis.methods),
                    "source_scope": analysis.source_scope,
                    "url": paper.url,
                }
            )

    recent_count, baseline_count = period_counts(
        result.papers,
        result.analyses,
        as_of=config.as_of,
        recent_days=config.recent_days,
        baseline_days=config.baseline_days,
    )
    generated_at = datetime.now(timezone.utc)
    manifest = {
        "schema_version": "0.2",
        "generated_at": generated_at.isoformat(),
        "topic": config.topic,
        "source": (
            "arXiv metadata, abstracts, and selected locally parsed PDFs"
            if result.pdf_documents
            else "arXiv metadata and abstracts only"
        ),
        "review_type": "exploratory arXiv trend scan; not a systematic review",
        "as_of": config.as_of.isoformat(),
        "recent_window": {
            "start": (config.as_of - timedelta(days=config.recent_days)).isoformat(),
            "end": config.as_of.isoformat(),
            "days": config.recent_days,
        },
        "baseline_window": {
            "start": (
                config.as_of - timedelta(days=config.recent_days + config.baseline_days)
            ).isoformat(),
            "end_exclusive": (config.as_of - timedelta(days=config.recent_days)).isoformat(),
            "days": config.baseline_days,
        },
        "backend": config.backend_name,
        "model": config.model_name or None,
        "settings": {
            "max_results_per_query": config.max_results,
            "min_candidates_before_broadening": config.min_candidates,
            "min_relevant_before_broadening": config.min_relevant,
            "refresh_cache": config.refresh_cache,
            "parse_pdfs": config.parse_pdfs,
            "max_pdfs": config.max_pdfs,
            "themes": json_ready(config.themes),
        },
        "search_plan": json_ready(result.plan),
        "executed_queries": result.executed_queries,
        "corpus_flow": {
            "unique_records_in_date_range": len(result.papers),
            "records_screened": len(result.analyses),
            "records_included": sum(item.relevant for item in result.analyses),
            "records_excluded": sum(not item.relevant for item in result.analyses),
            "recent_included": recent_count,
            "baseline_included": baseline_count,
        },
        "agent_trace": json_ready(result.agent_trace),
        "pdf_parsing": pdf_records,
        "warnings": result.warnings,
        "limitations": [
            "Preprints are not necessarily peer reviewed.",
            (
                "PDF text extraction is automatic and can contain reading-order or OCR errors."
                if result.pdf_documents
                else "Only titles, metadata, and abstracts were analyzed."
            ),
            "The result cap and query terms can omit relevant work.",
            "Trend signals are descriptive and sample-dependent.",
        ],
        "output_files": {key: str(path.name) for key, path in paths.items()},
    }
    paths["manifest"].write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    paths["report"].write_text(
        render_report(config, result, generated_at, recent_count, baseline_count),
        encoding="utf-8",
    )
    return paths


def render_report(
    config: WorkflowConfig,
    result: WorkflowResult,
    generated_at: datetime,
    recent_count: int,
    baseline_count: int,
) -> str:
    relevant_analyses = [analysis for analysis in result.analyses if analysis.relevant]
    analysis_by_id = {analysis.arxiv_id: analysis for analysis in result.analyses}
    recent_start = config.as_of - timedelta(days=config.recent_days)
    baseline_start = recent_start - timedelta(days=config.baseline_days)
    parsed_pdfs = [item for item in result.pdf_documents if item.status == "parsed"]
    failed_pdfs = [item for item in result.pdf_documents if item.status != "parsed"]
    scope_description = (
        "Exploratory arXiv metadata, abstract, and selected-PDF scan. Automatically extracted "
        "PDF text was used where available, but full-paper claims were not independently verified."
        if parsed_pdfs
        else "Exploratory arXiv metadata and abstract scan. No full-paper claims were verified."
    )
    lines = [
        f"# arXiv trend scan: {config.topic}",
        "",
        f"Generated: {generated_at.date().isoformat()} | As-of date: {config.as_of.isoformat()}",
        "",
        f"> **Scope:** {scope_description} This is not a systematic review.",
        "",
        "## Search record",
        "",
        "- Source: "
        + (
            "arXiv API metadata, abstracts, and selected locally parsed PDFs"
            if parsed_pdfs
            else "arXiv API metadata and abstracts"
        ),
        f"- Recent window: {recent_start.isoformat()} through {config.as_of.isoformat()} "
        f"({recent_count} included {_paper_word(recent_count)})",
        f"- Baseline window: {baseline_start.isoformat()} through "
        f"{(recent_start - timedelta(days=1)).isoformat()} "
        f"({baseline_count} included {_paper_word(baseline_count)})",
        f"- Backend: {config.backend_name}"
        + (f" (`{config.model_name}`)" if config.model_name else ""),
        f"- Unique records screened: {len(result.analyses)}",
        f"- Relevant records included: {len(relevant_analyses)}",
        f"- PDFs parsed locally: {len(parsed_pdfs)}"
        + (f" ({len(failed_pdfs)} failed)" if failed_pdfs else ""),
        "- Inclusion rule: topic relevance based on title and abstract",
        "- Exclusion rule: insufficient topic match or outside the configured date windows",
        "",
        "### Executed queries",
        "",
    ]
    for index, item in enumerate(result.executed_queries, start=1):
        lines.append(
            f"{index}. **{item['period']}** — `{item['query']}` — "
            f"{item['returned_records']} returned "
            f"({item['unique_in_window_after_merge']} unique records in scope; "
            f"cache: {'yes' if item['from_cache'] else 'no'})"
        )

    if result.pdf_documents:
        lines.extend(
            [
                "",
                "### PDF extraction record",
                "",
                "| arXiv ID | Status | Pages extracted | Characters | Detected sections |",
                "|---|---|---:|---:|---|",
            ]
        )
        for document in result.pdf_documents:
            sections = ", ".join(document.sections) or "—"
            lines.append(
                f"| [{document.arxiv_id}](https://arxiv.org/abs/{document.arxiv_id}) | "
                f"{document.status} | {document.pages_extracted} | "
                f"{document.extracted_chars:,} | {sections} |"
            )

    lines.extend(
        [
            "",
            "## Trend signals",
            "",
            "| Theme | Recent | Baseline | Recent share | Baseline share | Change | Signal |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for trend in result.trends:
        lines.append(
            f"| {trend.theme} | {trend.recent_count} | {trend.baseline_count} | "
            f"{trend.recent_share:.0%} | {trend.baseline_share:.0%} | "
            f"{trend.change_percentage_points:+.1f} pp | {trend.direction} |"
        )

    lines.extend(["", "## Evidence-linked observations", ""])
    if not result.insights:
        lines.append(
            "The included sample is too small to produce an observation with at least two "
            "supporting papers."
        )
    for insight in result.insights:
        links = ", ".join(
            f"[{paper_id}](https://arxiv.org/abs/{paper_id})" for paper_id in insight.supporting_ids
        )
        lines.append(
            f"- **{insight.theme} ({insight.confidence}):** {insight.claim} Evidence: {links}."
        )

    counts = method_counts(relevant_analyses)
    lines.extend(["", "## Methods named in included evidence", ""])
    if counts:
        for method, count in counts.most_common(12):
            lines.append(f"- {method}: {count}")
    else:
        lines.append("No method keyword met the transparent extraction rules.")

    lines.extend(
        [
            "",
            "## Included papers",
            "",
            "| Date | Paper | Evidence | Themes | Evidence-grounded summary |",
            "|---|---|---|---|---|",
        ]
    )
    for paper in result.papers:
        analysis = analysis_by_id[paper.arxiv_id]
        if not analysis.relevant:
            continue
        summary = analysis.summary.replace("|", "\\|")
        themes = ", ".join(analysis.themes) or "Unclassified"
        lines.append(
            f"| {paper.published.date().isoformat()} | "
            f"[{paper.title}]({paper.url}) | {analysis.source_scope} | {themes} | {summary} |"
        )

    category_counts = Counter(
        category
        for paper in result.papers
        if analysis_by_id[paper.arxiv_id].relevant
        for category in paper.categories
    )
    lines.extend(["", "## Coverage and limitations", ""])
    if category_counts:
        top_category, top_count = category_counts.most_common(1)[0]
        concentration = top_count / max(1, len(relevant_analyses))
        if concentration >= 0.7:
            lines.append(
                f"- **Coverage advisory:** `{top_category}` appears on {top_count}/"
                f"{len(relevant_analyses)} included records ({concentration:.0%}). This is a "
                "distribution signal, not a defect; conclusions may reflect that category."
            )
    lines.extend(
        [
            "- arXiv papers are preprints and may not be peer reviewed.",
            (
                "- Selected PDFs were parsed automatically; reading order, equations, tables, "
                "and scanned pages may be incomplete or incorrect."
                if parsed_pdfs
                else "- The workflow analyzed metadata and abstracts, not PDFs, appendices, code, "
                "or data."
            ),
            "- Abstract-level descriptions remain the fallback when a PDF was not selected or failed.",
            "- Query wording, theme keywords, date windows, and result caps affect the sample.",
            "- Percentage-point changes are descriptive signals; they do not establish a causal "
            "change in the field.",
            "",
            "## AI assistance disclosure",
            "",
        ]
    )
    if config.backend_name == "openai":
        lines.append(
            "OpenAI Structured Outputs assisted with query planning, evidence screening, and "
            "wording of trend observations. Retrieval, version merging, date filtering, counts, "
            "share changes, and evidence-ID validation were deterministic. Model failures were "
            "allowed to fall back to transparent heuristic rules and are recorded in `run_manifest.json`."
        )
    else:
        lines.append(
            "This run used deterministic agent policies for query planning, abstract screening, "
            "and trend wording. No external language-model call was made."
        )
    lines.append("")
    return "\n".join(lines)


def _paper_word(count: int) -> str:
    return "paper" if count == 1 else "papers"

