from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from .agents import default_themes
from .arxiv_client import ArxivClient, ArxivClientError
from .llm import OpenAIBackend
from .models import ThemeDefinition, WorkflowConfig
from .pdf_parser import PDFParser
from .workflow import TrendWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan arXiv evidence with a reproducible three-agent trend workflow and optional "
            "local PDF parsing."
        )
    )
    parser.add_argument("--topic", required=True, help="Research topic to scan.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: outputs/<as-of>-<topic-slug>).",
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--recent-days", type=_positive_int, default=180)
    parser.add_argument("--baseline-days", type=_positive_int, default=730)
    parser.add_argument("--max-results", type=_positive_int, default=80)
    parser.add_argument("--min-candidates", type=_positive_int, default=8)
    parser.add_argument("--min-relevant", type=_positive_int, default=5)
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Optional exact arXiv search_query. May be supplied twice.",
    )
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        metavar="NAME=KEYWORD1,KEYWORD2",
        help="Theme definition. Repeat for multiple themes.",
    )
    parser.add_argument("--backend", choices=("heuristic", "openai"), default="heuristic")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument(
        "--offline-feed",
        type=Path,
        help="Read a local Atom XML feed instead of contacting arXiv.",
    )
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument(
        "--parse-pdfs",
        action="store_true",
        help="Download and locally extract a balanced subset of relevant arXiv PDFs.",
    )
    parser.add_argument(
        "--max-pdfs",
        type=_positive_int,
        default=5,
        help="Maximum PDFs to parse when --parse-pdfs is enabled (default: 5).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        themes = _parse_themes(args.theme) if args.theme else default_themes(args.topic)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    output = args.output or Path("outputs") / f"{args.as_of.isoformat()}-{_slug(args.topic)}"
    backend = None
    if args.backend == "openai":
        try:
            backend = OpenAIBackend(args.model)
        except RuntimeError as exc:
            parser.error(str(exc))

    config = WorkflowConfig(
        topic=args.topic,
        output_dir=output,
        as_of=args.as_of,
        recent_days=args.recent_days,
        baseline_days=args.baseline_days,
        max_results=args.max_results,
        min_candidates=args.min_candidates,
        min_relevant=args.min_relevant,
        themes=themes,
        explicit_queries=tuple(args.query[:2]),
        backend_name=args.backend,
        model_name=args.model if args.backend == "openai" else "",
        refresh_cache=args.refresh_cache,
        parse_pdfs=args.parse_pdfs,
        max_pdfs=args.max_pdfs,
    )
    client = ArxivClient(
        Path("cache"),
        feed_path=args.offline_feed,
    )
    try:
        pdf_parser = PDFParser(Path("cache") / "pdfs") if args.parse_pdfs else None
        result, paths = TrendWorkflow(
            client,
            backend,
            pdf_parser=pdf_parser,
        ).run(config)
    except (ArxivClientError, OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")

    print(f"Included papers: {sum(item.relevant for item in result.analyses)}")
    print(f"Report: {Path(paths['report']).resolve()}")
    print(f"Manifest: {Path(paths['manifest']).resolve()}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    return 0


def _parse_themes(values: list[str]) -> tuple[ThemeDefinition, ...]:
    themes: list[ThemeDefinition] = []
    for value in values:
        if "=" not in value:
            raise argparse.ArgumentTypeError(
                f"Invalid theme {value!r}; expected NAME=KEYWORD1,KEYWORD2"
            )
        name, raw_keywords = value.split("=", 1)
        keywords = tuple(
            keyword.strip().lower() for keyword in raw_keywords.split(",") if keyword.strip()
        )
        if not name.strip() or not keywords:
            raise argparse.ArgumentTypeError(
                f"Invalid theme {value!r}; name and at least one keyword are required"
            )
        themes.append(ThemeDefinition(name.strip(), keywords))
    return tuple(themes)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "topic"

