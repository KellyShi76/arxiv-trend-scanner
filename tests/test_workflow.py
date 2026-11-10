from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from arxiv_trend_agent.arxiv_client import ArxivClient
from arxiv_trend_agent.models import PDFDocument, ThemeDefinition, WorkflowConfig
from arxiv_trend_agent.workflow import TrendWorkflow


FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


class WorkflowTests(unittest.TestCase):
    def test_offline_workflow_writes_auditable_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = WorkflowConfig(
                topic="causal longitudinal personalized treatment effects",
                output_dir=root / "output",
                as_of=date(2026, 11, 10),
                recent_days=180,
                baseline_days=365,
                max_results=20,
                min_candidates=2,
                min_relevant=2,
                themes=(
                    ThemeDefinition("Personalization", ("personalized", "heterogeneous", "individualized")),
                    ThemeDefinition("Doubly robust", ("doubly robust", "orthogonal")),
                ),
            )
            client = ArxivClient(root / "cache", feed_path=FIXTURE)
            result, paths = TrendWorkflow(client).run(config)

            self.assertGreaterEqual(sum(item.relevant for item in result.analyses), 3)
            self.assertEqual(sum(not item.relevant for item in result.analyses), 1)
            self.assertTrue(paths["report"].exists())
            self.assertTrue(paths["papers_json"].exists())
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["review_type"], "exploratory arXiv trend scan; not a systematic review")
            self.assertEqual(manifest["backend"], "heuristic")
            self.assertIn("agent_trace", manifest)
            self.assertEqual(
                {item["period"] for item in manifest["executed_queries"]},
                {"recent", "baseline"},
            )

    def test_pdf_enrichment_does_not_export_extracted_text(self) -> None:
        class FakePDFParser:
            @staticmethod
            def parse_paper(paper, refresh=False):
                return PDFDocument(
                    arxiv_id=paper.arxiv_id,
                    status="parsed",
                    source_url=paper.pdf_url,
                    pdf_path=f"cache/pdfs/{paper.arxiv_id}.pdf",
                    page_count=8,
                    pages_extracted=8,
                    extracted_chars=1200,
                    text_sha256="abc123",
                    sections=("methods", "results"),
                    analysis_text=(
                        "Methods We use a transformer and doubly robust estimation. "
                        "Results The estimator is evaluated on longitudinal observations."
                    ),
                )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = WorkflowConfig(
                topic="causal inference for longitudinal data and personalized treatment effects",
                output_dir=root / "output",
                as_of=date(2026, 11, 10),
                recent_days=180,
                baseline_days=365,
                max_results=20,
                min_candidates=2,
                min_relevant=2,
                themes=(
                    ThemeDefinition("Personalization", ("personalized", "heterogeneous", "individualized")),
                    ThemeDefinition("Doubly robust", ("doubly robust", "orthogonal")),
                ),
                parse_pdfs=True,
                max_pdfs=2,
            )
            client = ArxivClient(root / "cache", feed_path=FIXTURE)
            result, paths = TrendWorkflow(client, pdf_parser=FakePDFParser()).run(config)

            self.assertEqual(len(result.pdf_documents), 2)
            self.assertTrue(any(item.source_scope == "pdf_full_text" for item in result.analyses))
            exported = json.loads(paths["pdf_extraction"].read_text(encoding="utf-8"))
            self.assertNotIn("analysis_text", exported[0])
            self.assertEqual(exported[0]["text_sha256"], "abc123")


if __name__ == "__main__":
    unittest.main()

