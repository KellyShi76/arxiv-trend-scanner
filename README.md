# arXiv Trend Scanner

`arxiv-trend-agent` is a small, auditable agentic workflow that scans arXiv evidence for a topic, screens papers, and produces an evidence-linked trend report. It includes a command-line interface and a local browser interface.

It is designed as a research utility rather than a claim that an automated **systematic review** has been completed. Version 0.2 can optionally download and parse a capped subset of arXiv PDFs, but extracted text is still machine-read evidence—not independent verification.

![arXiv Trend Scanner web interface](docs/arxiv-trend-scanner.jpg)

## Engineering highlights

- **Agentic workflow:** query-planning, paper-analysis, and trend-synthesis agents cooperate through typed data contracts rather than free-form handoffs.
- **Grounded model integration:** the optional OpenAI backend uses the Responses API with Structured Outputs, treats paper text as untrusted input, and validates model-generated themes and evidence IDs before reporting them.
- **Deterministic research pipeline:** retrieval windows, arXiv-version deduplication, trend calculations, evidence gates, and reproducibility manifests remain outside the language model.
- **Full-text enrichment:** a bounded PDF pipeline downloads, caches, hashes, and parses a balanced subset of recent and baseline papers while excluding extracted full text from exported artifacts.
- **Two usable interfaces:** a FastAPI application runs scans as background jobs for the browser UI, while the same workflow is available through a packaged command-line interface.
- **Testable offline behavior:** synthetic arXiv fixtures exercise the workflow without network or model access, and GitHub Actions runs the test suite on every push and pull request.

## What the three agents do

```text
Topic
  │
  ▼
Query Planner Agent ── creates focused and fallback arXiv queries
  │
  ▼
arXiv client ── retrieves/caches Atom metadata and merges paper versions
  │
  ▼
optional PDF parser ── balances recent/baseline selection and extracts local text
  │
  ▼
Paper Analyst Agent ── screens relevance and analyzes available evidence
  │
  ▼
deterministic trend calculator ── compares recent and baseline theme shares
  │
  ▼
Trend Analyst Agent ── turns only validated statistics into cited observations
  │
  ▼
Markdown report + JSON/CSV evidence + reproducibility manifest
```

The controller can broaden the search once when the focused query produces too few candidates. Model-generated trend statements pass through an evidence gate: unknown themes, unknown arXiv IDs, and statements with too little support are rejected.

## Why there are two modes

- **Heuristic mode (default):** no API key or hosted model is required. The same agent boundaries run with transparent keyword and extractive policies, which makes tests and demos reproducible.
- **OpenAI mode (optional):** uses the Responses API and Structured Outputs for query planning, paper analysis, and trend synthesis. Deterministic retrieval, date windows, counting, deduplication, and evidence validation remain outside the model.

This separation makes model behavior replaceable and keeps numerical trend claims testable.

## Quick start

Python 3.10 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The only required package is `certifi`, used to keep HTTPS certificate verification reliable across Python installations. Certificate checks are never disabled.

## Local web interface

Install the browser app and PDF support:

```bash
python -m pip install -e '.[web]'
arxiv-trends-web
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The server binds only to `127.0.0.1`, so it is not exposed to other computers on the network.

The interface lets you choose the topic, date windows, result cap, analysis mode, theme taxonomy, and whether to parse PDFs. Long-running scans execute in the background while the page displays progress. Completed reports and evidence files can be viewed or downloaded in the browser.

Run the included offline demo first:

```bash
python -m arxiv_trend_agent \
  --topic "causal inference for longitudinal data and personalized treatment effects" \
  --as-of 2026-11-10 \
  --recent-days 180 \
  --baseline-days 365 \
  --offline-feed tests/fixtures/sample_feed.xml \
  --theme "Personalization=personalized,personalization,heterogeneous,individualized" \
  --theme "Longitudinal modeling=longitudinal,sequential,recurrent,rnn,transformer" \
  --theme "Doubly robust estimation=doubly robust,orthogonal,propensity" \
  --output outputs/offline-demo
```

Run a live arXiv scan:

```bash
python -m arxiv_trend_agent \
  --topic "causal inference for longitudinal data and personalized treatment effects" \
  --recent-days 180 \
  --baseline-days 730 \
  --max-results 80 \
  --output outputs/causal-trends
```

Add bounded PDF parsing:

```bash
python -m pip install -e '.[pdf]'
python -m arxiv_trend_agent \
  --topic "causal inference for longitudinal data and personalized treatment effects" \
  --recent-days 180 \
  --baseline-days 730 \
  --max-results 30 \
  --parse-pdfs \
  --max-pdfs 4 \
  --output outputs/causal-trends-with-pdfs
```

PDF selection alternates between the recent and baseline windows so the configured cap does not enrich only the newest papers. Downloads are sequential, cached under `cache/pdfs/`, limited to 50 MB and 200 pages per paper, and never committed by the supplied `.gitignore`. Text is extracted with reading-order sorting using [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/app1.html).

The workflow queries the recent and baseline date windows separately so a high-volume recent period cannot crowd the baseline out of a fixed result cap. The client makes requests sequentially, caches responses, and waits at least three seconds between live requests in accordance with the [arXiv API Terms of Use](https://info.arxiv.org/help/api/tou.html). Query construction, `submittedDate` filters, and the Atom response format follow the [arXiv API manual](https://info.arxiv.org/help/api/user-manual.html).

## Optional model-backed run

Install the optional packages and provide an API key through your environment:

```bash
python -m pip install -e '.[ai]'
read -s OPENAI_API_KEY
export OPENAI_API_KEY
echo
python -m arxiv_trend_agent \
  --backend openai \
  --model gpt-6-astra \
  --topic "causal inference for longitudinal data and personalized treatment effects" \
  --max-results 40 \
  --output outputs/model-backed-demo
```

The model name can be changed with `--model`. The implementation uses the [Responses API](https://developers.openai.com/api/docs/guides/text?lang=python) and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses). Retrieved abstracts and PDF text are explicitly treated as untrusted data, not as instructions.

## Outputs

Each run writes:

- `trend_report.md` — readable report with search scope, trend statistics, evidence links, and limitations.
- `papers.json` — retrieved metadata plus screening, evidence scope, and analysis.
- `papers.csv` — compact table for inspection.
- `pdf_extraction.json` — PDF provenance, page counts, hashes, section labels, and errors; extracted full text is deliberately excluded.
- `run_manifest.json` — timestamp, exact queries, date windows, settings, corpus counts, agent trace, and warnings.

Scheduled monitoring, embeddings/vector search, OCR, and citation-network analysis remain outside the current scope.

## Reproducibility and safety choices

- The exact topic, queries, search time, date windows, backend, and model are recorded.
- arXiv versions are merged by canonical identifier; the latest updated record is kept.
- Every paper is labeled `abstract_only` or `pdf_full_text` according to the evidence actually supplied to the analyst.
- External abstracts and PDF text are never allowed to modify the workflow or its inclusion rules.
- Downloaded PDFs remain in a local ignored cache; exported JSON records hashes and extraction metadata, not full text.
- PDF size, page count, and analysis-text length are bounded.
- Trend direction is calculated from counts and shares, not invented by a language model.
- Model failures fall back to the deterministic policy and are recorded in the manifest.
- Reports state when evidence is too sparse to support a trend claim.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The core test suite runs offline against a synthetic Atom feed. The PDF extraction test creates its own temporary PDF and is skipped when the optional PDF package is not installed.

## Current limitations

- arXiv is a preprint repository; inclusion does not imply peer review or independent verification.
- Abstracts can omit methods, null results, and important limitations.
- PDF text extraction can misread multi-column layouts, equations, tables, or scanned pages; OCR is not included.
- Keyword themes are transparent but imperfect; model-backed classification can also be wrong.
- A fixed `max-results` sample can miss papers in high-volume topics.
- Share changes are descriptive signals, not causal evidence about the field.

