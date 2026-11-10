from __future__ import annotations

import hashlib
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import certifi

from .models import Paper, SearchResponse


ATOM = "http://www.w3.org/2005/Atom"
OPEN_SEARCH = "http://a9.com/-/spec/opensearch/1.1/"
ARXIV = "http://arxiv.org/schemas/atom"
NAMESPACES = {"atom": ATOM, "opensearch": OPEN_SEARCH, "arxiv": ARXIV}


class ArxivClientError(RuntimeError):
    """Raised when arXiv cannot be queried or parsed."""


class ArxivClient:
    API_URL = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        cache_dir: Path,
        *,
        feed_path: Path | None = None,
        request_interval: float = 3.1,
        timeout: float = 30.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.feed_path = feed_path
        self.request_interval = request_interval
        self.timeout = timeout
        self._last_request_at = 0.0

    def search(
        self,
        query: str,
        *,
        max_results: int,
        refresh: bool = False,
    ) -> SearchResponse:
        params = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        request_url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"

        if self.feed_path is not None:
            raw = self.feed_path.read_bytes()
            papers, total = parse_atom_feed(raw)
            return SearchResponse(papers, total, request_url, True)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(request_url.encode("utf-8")).hexdigest()[:20]
        cache_path = self.cache_dir / f"{cache_key}.xml"
        if cache_path.exists() and not refresh:
            raw = cache_path.read_bytes()
            papers, total = parse_atom_feed(raw)
            return SearchResponse(papers, total, request_url, True)

        self._respect_rate_limit()
        request = urllib.request.Request(
            request_url,
            headers={
                "User-Agent": (
                    "arxiv-trend-agent/0.1 "
                    "(research metadata client; contact via project repository)"
                )
            },
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=context,
            ) as response:
                raw = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise ArxivClientError(f"arXiv request failed: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()

        papers, total = parse_atom_feed(raw)
        cache_path.write_bytes(raw)
        return SearchResponse(papers, total, request_url, False)

    def _respect_rate_limit(self) -> None:
        if self._last_request_at <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)


def parse_atom_feed(raw: bytes) -> tuple[list[Paper], int]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ArxivClientError(f"Invalid Atom response: {exc}") from exc

    total_text = root.findtext("opensearch:totalResults", default="0", namespaces=NAMESPACES)
    try:
        total_results = int(total_text)
    except ValueError:
        total_results = 0

    papers: list[Paper] = []
    for entry in root.findall("atom:entry", NAMESPACES):
        entry_url = _text(entry, "atom:id")
        versioned_id = entry_url.rstrip("/").split("/")[-1]
        canonical_id = re.sub(r"v\d+$", "", versioned_id)
        links = {
            link.attrib.get("rel", ""): link.attrib.get("href", "")
            for link in entry.findall("atom:link", NAMESPACES)
        }
        pdf_url = next(
            (
                link.attrib.get("href", "")
                for link in entry.findall("atom:link", NAMESPACES)
                if link.attrib.get("title") == "pdf"
            ),
            "",
        )
        authors = tuple(
            _clean(author.findtext(f"{{{ATOM}}}name", default=""))
            for author in entry.findall("atom:author", NAMESPACES)
        )
        categories = tuple(
            category.attrib.get("term", "")
            for category in entry.findall("atom:category", NAMESPACES)
            if category.attrib.get("term")
        )
        papers.append(
            Paper(
                arxiv_id=canonical_id,
                versioned_id=versioned_id,
                title=_clean(_text(entry, "atom:title")),
                authors=tuple(author for author in authors if author),
                abstract=_clean(_text(entry, "atom:summary")),
                published=_parse_datetime(_text(entry, "atom:published")),
                updated=_parse_datetime(_text(entry, "atom:updated")),
                categories=categories,
                url=links.get("alternate", entry_url),
                pdf_url=pdf_url,
            )
        )
    return papers, total_results


def merge_versions(papers: list[Paper]) -> list[Paper]:
    """Keep the most recently updated record for each canonical arXiv ID."""
    latest: dict[str, Paper] = {}
    for paper in papers:
        current = latest.get(paper.arxiv_id)
        if current is None or paper.updated > current.updated:
            latest[paper.arxiv_id] = paper
    return sorted(latest.values(), key=lambda paper: paper.published, reverse=True)


def _text(entry: ET.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=NAMESPACES)


def _clean(value: str) -> str:
    return " ".join(value.split())


def _parse_datetime(value: str) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

