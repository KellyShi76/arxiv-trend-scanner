from datetime import date
from pathlib import Path
import unittest

from arxiv_trend_agent.agents import PaperAnalystAgent, QueryPlannerAgent
from arxiv_trend_agent.arxiv_client import merge_versions, parse_atom_feed
from arxiv_trend_agent.models import ThemeDefinition
from arxiv_trend_agent.trend import calculate_trends


FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


class TrendTests(unittest.TestCase):
    def test_trend_counts_are_deterministic(self) -> None:
        papers, _ = parse_atom_feed(FIXTURE.read_bytes())
        papers = merge_versions(papers)
        plan = QueryPlannerAgent().run(
            "causal longitudinal personalized treatment effects"
        )
        themes = (
            ThemeDefinition("Personalization", ("personalized", "heterogeneous", "individualized")),
            ThemeDefinition("Doubly robust", ("doubly robust", "orthogonal")),
        )
        analyst = PaperAnalystAgent()
        analyses = [analyst.run(plan.topic, paper, plan, themes) for paper in papers]
        trends = calculate_trends(
            papers,
            analyses,
            themes,
            as_of=date(2026, 11, 10),
            recent_days=180,
            baseline_days=365,
        )
        by_name = {trend.theme: trend for trend in trends}
        self.assertEqual(by_name["Doubly robust"].recent_count, 2)
        self.assertEqual(by_name["Doubly robust"].baseline_count, 0)
        self.assertEqual(by_name["Doubly robust"].direction, "emerging")


if __name__ == "__main__":
    unittest.main()

