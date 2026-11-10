from __future__ import annotations

import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .agents import default_themes
from .arxiv_client import ArxivClient
from .llm import OpenAIBackend
from .models import ThemeDefinition, WorkflowConfig
from .pdf_parser import PDFParser
from .workflow import TrendWorkflow


PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PACKAGE_ROOT / "static"
DOWNLOADABLE_FILES = {
    "trend_report.md",
    "papers.json",
    "papers.csv",
    "pdf_extraction.json",
    "run_manifest.json",
}


class ThemePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    keywords: list[str] = Field(min_length=1, max_length=20)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("Each theme needs at least one keyword")
        return cleaned


class RunPayload(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    as_of: date = Field(default_factory=date.today)
    recent_days: int = Field(default=180, ge=1, le=3650)
    baseline_days: int = Field(default=730, ge=1, le=7300)
    max_results: int = Field(default=30, ge=1, le=200)
    backend: Literal["heuristic", "openai"] = "heuristic"
    model: str = Field(default="gpt-6-astra", min_length=1, max_length=100)
    parse_pdfs: bool = False
    max_pdfs: int = Field(default=4, ge=1, le=20)
    themes: list[ThemePayload] = Field(default_factory=list, max_length=12)

    @field_validator("topic", "model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


@dataclass(slots=True)
class Job:
    job_id: str
    status: str = "queued"
    progress: int = 0
    message: str = "Waiting to start"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str = ""
    output_dir: str = ""
    error: str = ""
    files: list[str] = field(default_factory=list)
    summary: dict[str, object] = field(default_factory=dict)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return Job(**asdict(job))

    def update(self, job_id: str, **values: object) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in values.items():
                setattr(job, key, value)


store = JobStore()
app = FastAPI(
    title="arXiv Trend Scanner",
    version="0.2.0",
    description="Local interface for reproducible arXiv trend scans.",
)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "arxiv-trend-scanner"}


@app.post("/api/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(payload: RunPayload, background_tasks: BackgroundTasks) -> dict[str, object]:
    job = store.create()
    background_tasks.add_task(_run_job, job.job_id, payload)
    return _public_job(job)


@app.get("/api/runs/{job_id}")
def get_run(job_id: str) -> dict[str, object]:
    return _public_job(_get_job(job_id))


@app.get("/api/runs/{job_id}/report", response_class=PlainTextResponse)
def get_report(job_id: str) -> PlainTextResponse:
    job = _get_job(job_id)
    path = _completed_file(job, "trend_report.md")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/runs/{job_id}/files/{filename}")
def download_file(job_id: str, filename: str) -> FileResponse:
    if filename not in DOWNLOADABLE_FILES:
        raise HTTPException(status_code=404, detail="Unknown output file")
    job = _get_job(job_id)
    path = _completed_file(job, filename)
    return FileResponse(path, filename=filename)


def _run_job(job_id: str, payload: RunPayload) -> None:
    store.update(job_id, status="running", progress=1, message="Starting the workflow")
    try:
        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_dir = Path.cwd() / "outputs" / f"web-{run_stamp}-{_slug(payload.topic)}-{job_id}"
        store.update(job_id, output_dir=str(output_dir))

        themes = (
            tuple(ThemeDefinition(item.name, tuple(item.keywords)) for item in payload.themes)
            if payload.themes
            else default_themes(payload.topic)
        )
        backend = OpenAIBackend(payload.model) if payload.backend == "openai" else None
        pdf_parser = PDFParser(Path.cwd() / "cache" / "pdfs") if payload.parse_pdfs else None
        config = WorkflowConfig(
            topic=payload.topic,
            output_dir=output_dir,
            as_of=payload.as_of,
            recent_days=payload.recent_days,
            baseline_days=payload.baseline_days,
            max_results=payload.max_results,
            min_candidates=min(8, payload.max_results),
            min_relevant=min(5, payload.max_results),
            themes=themes,
            backend_name=payload.backend,
            model_name=payload.model if payload.backend == "openai" else "",
            parse_pdfs=payload.parse_pdfs,
            max_pdfs=payload.max_pdfs,
        )
        client = ArxivClient(Path.cwd() / "cache" / "arxiv")
        workflow = TrendWorkflow(
            client,
            backend,
            pdf_parser=pdf_parser,
            progress=lambda percent, message: store.update(
                job_id,
                progress=percent,
                message=message,
            ),
        )
        result, paths = workflow.run(config)
        parsed_pdfs = sum(item.status == "parsed" for item in result.pdf_documents)
        store.update(
            job_id,
            status="complete",
            progress=100,
            message="Run complete",
            completed_at=datetime.now(timezone.utc).isoformat(),
            files=sorted(path.name for path in paths.values()),
            summary={
                "retrieved": len(result.papers),
                "included": sum(item.relevant for item in result.analyses),
                "insights": len(result.insights),
                "parsed_pdfs": parsed_pdfs,
                "warnings": result.warnings,
            },
        )
    except Exception as exc:
        store.update(
            job_id,
            status="failed",
            message="Run failed",
            error=str(exc)[:1000],
            completed_at=datetime.now(timezone.utc).isoformat(),
        )


def _get_job(job_id: str) -> Job:
    try:
        return store.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def _completed_file(job: Job, filename: str) -> Path:
    if job.status != "complete" or not job.output_dir:
        raise HTTPException(status_code=409, detail="Run is not complete")
    path = Path(job.output_dir) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")
    return path


def _public_job(job: Job) -> dict[str, object]:
    value = asdict(job)
    value.pop("output_dir", None)
    value["report_url"] = (
        f"/api/runs/{job.job_id}/report" if job.status == "complete" else ""
    )
    value["download_urls"] = {
        filename: f"/api/runs/{job.job_id}/files/{filename}"
        for filename in job.files
        if filename in DOWNLOADABLE_FILES
    }
    return value


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40] or "topic"


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "Web support is not installed. Run: python -m pip install -e '.[web]'"
        ) from exc
    port = int(os.environ.get("ARXIV_TREND_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()

