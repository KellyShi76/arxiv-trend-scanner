from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Paper:
    arxiv_id: str
    versioned_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    published: datetime
    updated: datetime
    categories: tuple[str, ...]
    url: str
    pdf_url: str = ""


@dataclass(slots=True)
class SearchResponse:
    papers: list[Paper]
    total_results: int
    request_url: str
    from_cache: bool


@dataclass(slots=True)
class SearchPlan:
    topic: str
    queries: tuple[str, ...]
    inclusion_terms: tuple[str, ...]
    scope_note: str


@dataclass(slots=True)
class ThemeDefinition:
    name: str
    keywords: tuple[str, ...]


@dataclass(slots=True)
class PaperAnalysis:
    arxiv_id: str
    relevant: bool
    relevance_score: float
    relevance_reason: str
    summary: str
    methods: tuple[str, ...]
    themes: tuple[str, ...]
    matched_terms: tuple[str, ...]
    source_scope: str = "abstract_only"
    evidence_sections: tuple[str, ...] = ()
    limitations: str = (
        "Abstract-only analysis; methods and results were not verified against the full text."
    )


@dataclass(slots=True)
class PDFDocument:
    arxiv_id: str
    status: str
    source_url: str
    pdf_path: str
    page_count: int
    pages_extracted: int
    extracted_chars: int
    text_sha256: str
    sections: tuple[str, ...]
    analysis_text: str = ""
    warning: str = ""


@dataclass(slots=True)
class ThemeTrend:
    theme: str
    recent_count: int
    baseline_count: int
    recent_share: float
    baseline_share: float
    change_percentage_points: float
    direction: str
    supporting_ids: tuple[str, ...]


@dataclass(slots=True)
class TrendInsight:
    theme: str
    claim: str
    supporting_ids: tuple[str, ...]
    confidence: str


@dataclass(slots=True)
class AgentEvent:
    agent: str
    mode: str
    detail: str


@dataclass(slots=True)
class WorkflowConfig:
    topic: str
    output_dir: Path
    as_of: date
    recent_days: int = 180
    baseline_days: int = 730
    max_results: int = 80
    min_candidates: int = 8
    min_relevant: int = 5
    themes: tuple[ThemeDefinition, ...] = ()
    explicit_queries: tuple[str, ...] = ()
    backend_name: str = "heuristic"
    model_name: str = ""
    refresh_cache: bool = False
    parse_pdfs: bool = False
    max_pdfs: int = 5


@dataclass(slots=True)
class WorkflowResult:
    plan: SearchPlan
    papers: list[Paper]
    analyses: list[PaperAnalysis]
    trends: list[ThemeTrend]
    insights: list[TrendInsight]
    executed_queries: list[dict[str, Any]]
    pdf_documents: list[PDFDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    agent_trace: list[AgentEvent] = field(default_factory=list)


def json_ready(value: Any) -> Any:
    """Convert project dataclasses to JSON-compatible values."""
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value

