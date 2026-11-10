from __future__ import annotations

from datetime import date, timedelta

from .models import Paper, PaperAnalysis, ThemeDefinition, ThemeTrend


def calculate_trends(
    papers: list[Paper],
    analyses: list[PaperAnalysis],
    themes: tuple[ThemeDefinition, ...],
    *,
    as_of: date,
    recent_days: int,
    baseline_days: int,
) -> list[ThemeTrend]:
    paper_by_id = {paper.arxiv_id: paper for paper in papers}
    relevant = [analysis for analysis in analyses if analysis.relevant]
    recent_start = as_of - timedelta(days=recent_days)
    baseline_start = recent_start - timedelta(days=baseline_days)

    recent = [
        analysis
        for analysis in relevant
        if recent_start <= paper_by_id[analysis.arxiv_id].published.date() <= as_of
    ]
    baseline = [
        analysis
        for analysis in relevant
        if baseline_start <= paper_by_id[analysis.arxiv_id].published.date() < recent_start
    ]

    trends: list[ThemeTrend] = []
    for theme in themes:
        recent_matches = [item for item in recent if theme.name in item.themes]
        baseline_matches = [item for item in baseline if theme.name in item.themes]
        recent_share = len(recent_matches) / len(recent) if recent else 0.0
        baseline_share = len(baseline_matches) / len(baseline) if baseline else 0.0
        change = (recent_share - baseline_share) * 100
        support = tuple(
            dict.fromkeys(
                [item.arxiv_id for item in recent_matches]
                + [item.arxiv_id for item in baseline_matches]
            )
        )
        direction = _direction(
            recent_count=len(recent_matches),
            baseline_count=len(baseline_matches),
            change_percentage_points=change,
        )
        trends.append(
            ThemeTrend(
                theme=theme.name,
                recent_count=len(recent_matches),
                baseline_count=len(baseline_matches),
                recent_share=recent_share,
                baseline_share=baseline_share,
                change_percentage_points=change,
                direction=direction,
                supporting_ids=support,
            )
        )
    return sorted(
        trends,
        key=lambda item: (abs(item.change_percentage_points), item.recent_count),
        reverse=True,
    )


def period_counts(
    papers: list[Paper],
    analyses: list[PaperAnalysis],
    *,
    as_of: date,
    recent_days: int,
    baseline_days: int,
) -> tuple[int, int]:
    paper_by_id = {paper.arxiv_id: paper for paper in papers}
    recent_start = as_of - timedelta(days=recent_days)
    baseline_start = recent_start - timedelta(days=baseline_days)
    recent = 0
    baseline = 0
    for analysis in analyses:
        if not analysis.relevant:
            continue
        published = paper_by_id[analysis.arxiv_id].published.date()
        if recent_start <= published <= as_of:
            recent += 1
        elif baseline_start <= published < recent_start:
            baseline += 1
    return recent, baseline


def _direction(*, recent_count: int, baseline_count: int, change_percentage_points: float) -> str:
    if recent_count >= 2 and baseline_count == 0:
        return "emerging"
    if recent_count >= 2 and change_percentage_points >= 5:
        return "increasing"
    if baseline_count >= 2 and change_percentage_points <= -5:
        return "declining"
    return "stable/insufficient"

