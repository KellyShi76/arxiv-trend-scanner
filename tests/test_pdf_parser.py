import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from arxiv_trend_agent.pdf_parser import PDFParser, pdf_metadata


@unittest.skipUnless(importlib.util.find_spec("pymupdf"), "PyMuPDF is optional")
class PDFParserTests(unittest.TestCase):
    def test_extracts_text_and_emits_metadata_without_full_text(self) -> None:
        import pymupdf

        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "Methods\nWe use a recurrent neural network.\nResults\nThe estimator converges.",
            )
            document.save(pdf_path)
            document.close()

            parsed = PDFParser(Path(tmp) / "cache").parse_file(
                "2601.00001",
                "https://arxiv.org/pdf/2601.00001",
                pdf_path,
            )

            self.assertEqual(parsed.status, "parsed")
            self.assertEqual(parsed.page_count, 1)
            self.assertIn("recurrent neural network", parsed.analysis_text)
            metadata = pdf_metadata(parsed)
            self.assertNotIn("analysis_text", metadata)
            self.assertEqual(metadata["text_sha256"], parsed.text_sha256)


if __name__ == "__main__":
    unittest.main()

