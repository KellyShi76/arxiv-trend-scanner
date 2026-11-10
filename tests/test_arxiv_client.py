from pathlib import Path
import unittest

from arxiv_trend_agent.arxiv_client import merge_versions, parse_atom_feed


FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


class ArxivClientTests(unittest.TestCase):
    def test_parse_and_merge_versions(self) -> None:
        papers, total = parse_atom_feed(FIXTURE.read_bytes())

        self.assertEqual(total, 6)
        self.assertEqual(len(papers), 6)
        merged = merge_versions(papers)
        self.assertEqual(len(merged), 5)
        updated = next(paper for paper in merged if paper.arxiv_id == "2609.00001")
        self.assertEqual(updated.versioned_id, "2609.00001v2")
        self.assertIn("updated identification", updated.abstract)


if __name__ == "__main__":
    unittest.main()

