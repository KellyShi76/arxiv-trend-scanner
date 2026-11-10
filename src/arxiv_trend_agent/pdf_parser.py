from __future__ import annotations

import hashlib
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import certifi

from .models import PDFDocument, Paper


SECTION_NAMES = (
    "abstract",
    "introduction",
    "background",
    "related work",
    "methods",
    "methodology",
    "materials and methods",
    "experiments",
    "results",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
)


class PDFParser:
    """Download and extract local text from a bounded number of arXiv PDFs."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        request_interval: float = 3.1,
        timeout: float = 60.0,
        max_bytes: int = 50 * 1024 * 1024,
        max_pages: int = 200,
        max_analysis_chars: int = 60_000,
    ) -> None:
        self.cache_dir = cache_dir
        self.request_interval = request_interval
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.max_analysis_chars = max_analysis_chars
        self._last_request_at = 0.0

    def parse_paper(self, paper: Paper, *, refresh: bool = False) -> PDFDocument:
        source_url = _pdf_url(paper)
        if not source_url:
            return _failed(paper, "No PDF URL was present in the arXiv metadata.")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", paper.arxiv_id)
        pdf_path = self.cache_dir / f"{safe_id}.pdf"
        try:
            if refresh or not pdf_path.exists():
                self._download(source_url, pdf_path)
            return self.parse_file(paper.arxiv_id, source_url, pdf_path)
        except Exception as exc:
            return PDFDocument(
                arxiv_id=paper.arxiv_id,
                status="failed",
                source_url=source_url,
                pdf_path=str(pdf_path),
                page_count=0,
                pages_extracted=0,
                extracted_chars=0,
                text_sha256="",
                sections=(),
                warning=str(exc)[:500],
            )

    def parse_file(self, arxiv_id: str, source_url: str, pdf_path: Path) -> PDFDocument:
        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError(
                "PDF support is not installed. Run: python -m pip install -e '.[pdf]'"
            ) from exc

        raw = pdf_path.read_bytes()
        if not raw.startswith(b"%PDF-"):
            raise ValueError("The downloaded file is not recognized as a PDF.")
        if len(raw) > self.max_bytes:
            raise ValueError(f"PDF exceeds the {self.max_bytes // (1024 * 1024)} MB limit.")

        with pymupdf.open(pdf_path) as document:
            if document.needs_pass:
                raise ValueError("Encrypted PDFs are not supported.")
            page_count = document.page_count
            pages_extracted = min(page_count, self.max_pages)
            page_text = [
                document.load_page(index).get_text("text", sort=True)
                for index in range(pages_extracted)
            ]

        full_text = _normalize_text("\n\n".join(page_text))
        if not full_text.strip():
            raise ValueError(
                "No extractable text was found; this may be a scanned or image-only PDF."
            )
        sections = _find_sections(full_text)
        analysis_text = _analysis_excerpt(full_text, self.max_analysis_chars)
        warning = ""
        if page_count > pages_extracted:
            warning = f"Extraction stopped after {pages_extracted} of {page_count} pages."
        return PDFDocument(
            arxiv_id=arxiv_id,
            status="parsed",
            source_url=source_url,
            pdf_path=str(pdf_path),
            page_count=page_count,
            pages_extracted=pages_extracted,
            extracted_chars=len(full_text),
            text_sha256=hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            sections=sections,
            analysis_text=analysis_text,
            warning=warning,
        )

    def _download(self, source_url: str, destination: Path) -> None:
        self._respect_rate_limit()
        request = urllib.request.Request(
            source_url,
            headers={
                "User-Agent": (
                    "arxiv-trend-agent/0.2 "
                    "(local research PDF reader; contact via project repository)"
                )
            },
        )
        temporary = destination.with_suffix(".pdf.part")
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=context,
            ) as response:
                declared_size = response.headers.get("Content-Length")
                if declared_size and int(declared_size) > self.max_bytes:
                    raise ValueError(
                        f"PDF exceeds the {self.max_bytes // (1024 * 1024)} MB limit."
                    )
                total = 0
                with temporary.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise ValueError(
                                f"PDF exceeds the {self.max_bytes // (1024 * 1024)} MB limit."
                            )
                        handle.write(chunk)
            if not temporary.read_bytes().startswith(b"%PDF-"):
                raise ValueError("arXiv returned a response that was not a PDF.")
            temporary.replace(destination)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"PDF download failed: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
            if temporary.exists():
                temporary.unlink()

    def _respect_rate_limit(self) -> None:
        if self._last_request_at <= 0:
            return
        remaining = self.request_interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)


def pdf_metadata(document: PDFDocument) -> dict[str, object]:
    """Return safe provenance fields without redistributing extracted full text."""
    path = Path(document.pdf_path) if document.pdf_path else None
    if path:
        try:
            display_path = str(path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            display_path = path.name
    else:
        display_path = ""
    return {
        "arxiv_id": document.arxiv_id,
        "status": document.status,
        "source_url": document.source_url,
        "pdf_path": display_path,
        "page_count": document.page_count,
        "pages_extracted": document.pages_extracted,
        "extracted_chars": document.extracted_chars,
        "text_sha256": document.text_sha256,
        "sections": list(document.sections),
        "warning": document.warning,
    }


def _pdf_url(paper: Paper) -> str:
    value = paper.pdf_url or f"https://arxiv.org/pdf/{paper.arxiv_id}"
    if value.startswith("http://"):
        value = "https://" + value.removeprefix("http://")
    return value


def _failed(paper: Paper, warning: str) -> PDFDocument:
    return PDFDocument(
        arxiv_id=paper.arxiv_id,
        status="failed",
        source_url=paper.pdf_url,
        pdf_path="",
        page_count=0,
        pages_extracted=0,
        extracted_chars=0,
        text_sha256="",
        sections=(),
        warning=warning,
    )


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    cleaned: list[str] = []
    empty = False
    for line in lines:
        if line:
            cleaned.append(line)
            empty = False
        elif not empty:
            cleaned.append("")
            empty = True
    return "\n".join(cleaned).strip()


def _find_sections(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for line in text.splitlines():
        normalized = re.sub(r"^[0-9IVXivx.\s-]+", "", line).strip().lower().rstrip(":")
        if normalized in SECTION_NAMES and normalized not in found:
            found.append(normalized)
    return tuple(found)


def _analysis_excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    beginning_size = min(20_000, limit // 3)
    ending_size = min(10_000, limit // 6)
    pieces = [text[:beginning_size]]
    heading_pattern = re.compile(
        r"(?im)^(?:\d+(?:\.\d+)*\s+)?"
        r"(methods?|methodology|experiments?|results?|discussion|limitations?|conclusions?)\s*$"
    )
    seen_starts: set[int] = set()
    remaining = limit - beginning_size - ending_size
    for match in heading_pattern.finditer(text):
        start = max(0, match.start() - 200)
        if any(abs(start - previous) < 2_000 for previous in seen_starts):
            continue
        seen_starts.add(start)
        take = min(8_000, max(0, remaining))
        if take <= 0:
            break
        pieces.append(text[start : start + take])
        remaining -= take
    if remaining > 0:
        middle = max(0, (len(text) - remaining) // 2)
        pieces.append(text[middle : middle + remaining])
    pieces.append(text[-ending_size:])
    return "\n\n[... section boundary ...]\n\n".join(pieces)[:limit]

