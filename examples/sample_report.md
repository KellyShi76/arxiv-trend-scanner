# Example arXiv trend scan (synthetic fixture)

> This file is generated from `tests/fixtures/sample_feed.xml`. The papers and authors in that fixture are synthetic and exist only to demonstrate the output contract.

## Scope

- Topic: causal inference for longitudinal data and personalized treatment effects
- Source surface: arXiv-style metadata and abstracts only
- Recent window: 2026-05-14 through 2026-11-10
- Baseline window: 2025-05-14 through 2026-05-13
- Unique records screened: 5
- Relevant records included: 4
- Review type: exploratory trend scan, not a systematic review

## Trend signals

| Theme | Recent | Baseline | Recent share | Baseline share | Change | Signal |
|---|---:|---:|---:|---:|---:|---|
| Longitudinal modeling | 3 | 0 | 100% | 0% | +100.0 pp | emerging |
| Doubly robust estimation | 2 | 0 | 67% | 0% | +66.7 pp | emerging |
| Personalization | 2 | 1 | 67% | 100% | -33.3 pp | stable/insufficient |

## Evidence-linked observations

- **Longitudinal modeling (preliminary):** The synthetic recent-window abstracts contain three longitudinal-modeling records and the baseline contains none. Evidence: `2609.00001`, `2608.00002`, `2606.00003`.
- **Doubly robust estimation (preliminary):** The synthetic recent-window abstracts contain two doubly robust records and the baseline contains none. Evidence: `2609.00001`, `2606.00003`.
- **Personalization (preliminary):** No strong directional claim is made because the baseline denominator contains only one included record.

## Example paper record

```json
{
  "arxiv_id": "2609.00001",
  "title": "Personalized causal effects for longitudinal continuous treatments",
  "source_scope": "arXiv metadata and abstract only",
  "analysis": {
    "relevant": true,
    "themes": [
      "Personalization",
      "Longitudinal modeling",
      "Doubly robust estimation"
    ],
    "methods": [
      "transformer",
      "doubly robust estimation",
      "causal inference"
    ],
    "limitations": "Abstract-only analysis; methods and results were not verified against the full text."
  }
}
```

## Interpretation limits

- All records in this example are synthetic.
- A live run analyzes preprints, which may not be peer reviewed.
- Theme shares describe the retrieved sample, not the entire field.
- Query wording, date windows, and result caps can change the apparent signal.

