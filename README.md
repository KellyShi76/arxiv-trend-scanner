# arXiv Trend Scanner

`arxiv-trend-agent` is a small, auditable agentic workflow that scans arXiv evidence for a topic, screens papers, and produces an evidence-linked trend report. It includes a command-line interface and a local browser interface.

Claim: It is designed for my own use as a research utility. 

![arXiv Trend Scanner web interface](docs/arxiv-trend-scanner.jpg)


## How it works

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

- **Heuristic mode (default):** no API key or hosted model is required. The same agent boundaries run with transparent keyword and extractive policies, which makes tests and demos reproducible.
- **OpenAI mode (optional):** uses the Responses API and Structured Outputs for query planning, paper analysis, and trend synthesis. Deterministic retrieval, date windows, counting, deduplication, and evidence validation remain outside the model.

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


