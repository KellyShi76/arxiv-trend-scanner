from pathlib import Path
import unittest

from arxiv_trend_agent.agents import (
    PaperAnalystAgent,
    QueryPlannerAgent,
    TrendAnalystAgent,
    topic_phrases,
)
from arxiv_trend_agent.arxiv_client import merge_versions, parse_atom_feed
from arxiv_trend_agent.models import ThemeDefinition, ThemeTrend


FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


class AgentTests(unittest.TestCase):
    def test_compact_topic_uses_an_exact_phrase(self) -> None:
        plan = QueryPlannerAgent().run("inverse reinforcement learning")
        self.assertEqual(plan.queries[0], 'all:"inverse reinforcement learning"')
        self.assertEqual(topic_phrases(plan.topic), ["inverse reinforcement learning"])

    def test_planner_and_abstract_screening(self) -> None:
        planner = QueryPlannerAgent()
        plan = planner.run(
            "causal inference for longitudinal data and personalized treatment effects"
        )
        self.assertGreaterEqual(len(plan.queries), 1)
        self.assertIn("causal", plan.inclusion_terms)

        papers, _ = parse_atom_feed(FIXTURE.read_bytes())
        paper = next(item for item in merge_versions(papers) if item.arxiv_id == "2609.00001")
        themes = (
            ThemeDefinition("Personalization", ("personalized", "heterogeneous")),
            ThemeDefinition("Longitudinal", ("longitudinal", "recurrent")),
        )
        analysis = PaperAnalystAgent().run(plan.topic, paper, plan, themes)
        self.assertTrue(analysis.relevant)
        self.assertIn("Personalization", analysis.themes)
        self.assertIn("Longitudinal", analysis.themes)
        self.assertIn("transformer", analysis.methods)

    def test_trend_agent_rejects_unknown_evidence(self) -> None:
        class FakeBackend:
            @staticmethod
            def synthesize_trends(topic, trends):
                return [
                    {
                        "theme": "Reward recovery",
                        "claim": "Abstracts suggest growing attention to reward recovery.",
                        "supporting_ids": ["2601.00001", "2601.00002"],
                        "confidence": "moderate",
                    },
                    {
                        "theme": "Invented theme",
                        "claim": "This should be rejected.",
                        "supporting_ids": ["9999.99999", "8888.88888"],
                        "confidence": "moderate",
                    },
                ]

        trends = [
            ThemeTrend(
                theme="Reward recovery",
                recent_count=2,
                baseline_count=0,
                recent_share=0.5,
                baseline_share=0.0,
                change_percentage_points=50.0,
                direction="emerging",
                supporting_ids=("2601.00001", "2601.00002"),
            )
        ]
        insights = TrendAnalystAgent(FakeBackend()).run("inverse RL", trends)
        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].theme, "Reward recovery")
        self.assertEqual(insights[0].supporting_ids, ("2601.00001", "2601.00002"))


if __name__ == "__main__":
    unittest.main()

