from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .models import (
    AgentEvent,
    Paper,
    PaperAnalysis,
    SearchPlan,
    ThemeDefinition,
    ThemeTrend,
    TrendInsight,
)


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "data",
    "effect",
    "effects",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "using",
    "with",
}

METHOD_KEYWORDS = {
    "transformer": ("transformer", "attention"),
    "recurrent neural network": ("recurrent neural network", "rnn", "lstm", "gru"),
    "deep neural network": ("deep neural", "dnn", "multilayer perceptron", "mlp"),
    "doubly robust estimation": ("doubly robust", "orthogonal score"),
    "causal inference": ("causal inference", "causal effect", "potential outcome"),
    "representation learning": ("representation learning", "embedding", "self-supervised"),
    "reinforcement learning": ("reinforcement learning", "policy", "markov decision"),
    "Bayesian modeling": ("bayesian", "posterior", "prior distribution"),
    "simulation": ("simulation", "synthetic experiment"),
}


class QueryPlannerAgent:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend
        self.events: list[AgentEvent] = []

    def run(self, topic: str, explicit_queries: tuple[str, ...] = ()) -> SearchPlan:
        fallback = self._heuristic_plan(topic, explicit_queries)
        if explicit_queries:
            self.events.append(
                AgentEvent("Query Planner Agent", "user-specified", "Used explicit arXiv queries.")
            )
            return fallback
        if self.backend is None:
            self.events.append(
                AgentEvent("Query Planner Agent", "heuristic", "Created focused and fallback queries.")
            )
            return fallback
        try:
            payload = self.backend.plan_queries(topic)
            queries = tuple(
                query.strip()
                for query in payload.get("queries", [])[:2]
                if _valid_arxiv_query(query)
            )
            terms = tuple(_unique_tokens(payload.get("inclusion_terms", [])))
            if not queries or not terms:
                raise ValueError("The model returned an empty or invalid search plan")
            self.events.append(
                AgentEvent("Query Planner Agent", "openai", "Generated a structured search plan.")
            )
            return SearchPlan(
                topic=topic,
                queries=queries,
                inclusion_terms=terms,
                scope_note=str(payload.get("scope_note", "arXiv metadata and abstracts only"))[:300],
            )
        except Exception as exc:  # fallback is part of the workflow contract
            self.events.append(
                AgentEvent(
                    "Query Planner Agent",
                    "heuristic-fallback",
                    f"Model planning failed; used deterministic plan: {exc}",
                )
            )
            return fallback

    @staticmethod
    def _heuristic_plan(topic: str, explicit_queries: tuple[str, ...]) -> SearchPlan:
        terms = topic_terms(topic)
        if explicit_queries:
            queries = tuple(query for query in explicit_queries[:2] if _valid_arxiv_query(query))
            if not queries:
                raise ValueError("No valid --query value was supplied")
        else:
            if not terms:
                raise ValueError("The topic must contain at least one meaningful search term")
            phrases = topic_phrases(topic)
            focused_units = phrases[:2] if phrases else terms[: min(3, len(terms))]
            broad_candidates = [
                term
                for term in terms
                if term not in {"analysis", "inference", "learning", "research", "study"}
            ]
            broad_terms = (broad_candidates or terms)[: min(2, len(broad_candidates or terms))]
            focused = " AND ".join(_query_unit(unit) for unit in focused_units)
            if phrases and " " in phrases[0]:
                broad = _query_unit(phrases[0])
            else:
                broad = " AND ".join(_query_unit(term) for term in broad_terms)
            queries = (focused,) if broad == focused else (focused, broad)
        return SearchPlan(
            topic=topic,
            queries=queries,
            inclusion_terms=tuple(terms),
            scope_note="arXiv metadata and abstract screening; no full-text verification",
        )


class PaperAnalystAgent:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend
        self.events: list[AgentEvent] = []
        self._fallback_count = 0

    def run(
        self,
        topic: str,
        paper: Paper,
        plan: SearchPlan,
        themes: tuple[ThemeDefinition, ...],
        *,
        full_text: str = "",
        evidence_sections: tuple[str, ...] = (),
    ) -> PaperAnalysis:
        fallback = self._heuristic_analysis(
            paper,
            plan,
            themes,
            full_text=full_text,
            evidence_sections=evidence_sections,
        )
        if self.backend is None:
            return fallback
        try:
            payload = self.backend.analyze_paper(
                topic,
                paper,
                themes,
                full_text=full_text,
                evidence_sections=evidence_sections,
            )
            allowed_themes = {theme.name for theme in themes}
            selected_themes = tuple(
                name for name in payload.get("themes", []) if name in allowed_themes
            )
            score = min(1.0, max(0.0, float(payload.get("relevance_score", 0.0))))
            analysis = PaperAnalysis(
                arxiv_id=paper.arxiv_id,
                relevant=bool(payload.get("relevant")),
                relevance_score=score,
                relevance_reason=str(payload.get("relevance_reason", ""))[:400],
                summary=str(payload.get("summary", ""))[:700],
                methods=tuple(_unique_strings(payload.get("methods", []), limit=8)),
                themes=selected_themes,
                matched_terms=tuple(_unique_strings(payload.get("matched_terms", []), limit=12)),
                source_scope="pdf_full_text" if full_text else "abstract_only",
                evidence_sections=tuple(
                    _unique_strings(payload.get("evidence_sections", []), limit=10)
                )
                or evidence_sections,
                limitations=(
                    "PDF text was extracted automatically and may have reading-order or OCR "
                    "errors; claims were not independently verified."
                    if full_text
                    else "Abstract-only analysis; methods and results were not verified against "
                    "the full text."
                ),
            )
            if analysis.relevant and not analysis.summary:
                raise ValueError("Relevant paper had no summary")
            return analysis
        except Exception as exc:
            self._fallback_count += 1
            if self._fallback_count <= 3:
                self.events.append(
                    AgentEvent(
                        "Paper Analyst Agent",
                        "heuristic-fallback",
                        f"Used deterministic analysis for {paper.arxiv_id}: {exc}",
                    )
                )
            return fallback

    def finish(self, analyzed_count: int, *, full_text_count: int = 0) -> None:
        if self.backend is None:
            self.events.append(
                AgentEvent(
                    "Paper Analyst Agent",
                    "heuristic",
                    f"Screened {analyzed_count} records with transparent rules; "
                    f"used locally extracted PDF text for {full_text_count}.",
                )
            )
        else:
            model_count = analyzed_count - self._fallback_count
            self.events.append(
                AgentEvent(
                    "Paper Analyst Agent",
                    "openai",
                    f"Structured model analyses: {model_count}; deterministic fallbacks: "
                    f"{self._fallback_count}; PDF-backed records: {full_text_count}.",
                )
            )

    @staticmethod
    def _heuristic_analysis(
        paper: Paper,
        plan: SearchPlan,
        themes: tuple[ThemeDefinition, ...],
        *,
        full_text: str = "",
        evidence_sections: tuple[str, ...] = (),
    ) -> PaperAnalysis:
        title_lower = paper.title.lower()
        screening_text = f"{paper.title} {paper.abstract}".lower()
        analysis_text = (
            f"{paper.title} {paper.abstract} {full_text}".lower()
            if full_text
            else screening_text
        )
        matched = tuple(
            term for term in plan.inclusion_terms if _contains(screening_text, term)
        )
        title_matches = sum(1 for term in plan.inclusion_terms if _contains(title_lower, term))
        denominator = max(1, len(plan.inclusion_terms) * 2)
        score = min(1.0, (len(matched) + title_matches) / denominator)

        methods = tuple(
            method
            for method, keywords in METHOD_KEYWORDS.items()
            if any(_contains(analysis_text, keyword) for keyword in keywords)
        )
        matched_themes = tuple(
            theme.name
            for theme in themes
            if any(_contains(analysis_text, keyword.lower()) for keyword in theme.keywords)
        )
        screening_themes = tuple(
            theme.name
            for theme in themes
            if any(_contains(screening_text, keyword.lower()) for keyword in theme.keywords)
        )
        phrases = topic_phrases(plan.topic)
        phrase_matches = tuple(
            phrase for phrase in phrases if _contains(screening_text, phrase)
        )
        compact_topic = len(plan.inclusion_terms) <= 4 and len(phrases) == 1
        if compact_topic:
            relevant = bool(phrase_matches)
        else:
            relevant = (
                bool(phrase_matches) and len(matched) >= 2
            ) or title_matches >= 2 or (bool(screening_themes) and len(matched) >= 1)
        summary = _extractive_summary(paper.abstract)
        reason = (
            f"Matched {len(matched)} topic term(s): {', '.join(matched) or 'none'}. "
            f"Matched phrases: {', '.join(phrase_matches) or 'none'}. "
            f"Title matches: {title_matches}."
        )
        return PaperAnalysis(
            arxiv_id=paper.arxiv_id,
            relevant=relevant,
            relevance_score=round(score, 3),
            relevance_reason=reason,
            summary=summary,
            methods=methods,
            themes=matched_themes,
            matched_terms=matched,
            source_scope="pdf_full_text" if full_text else "abstract_only",
            evidence_sections=evidence_sections,
            limitations=(
                "PDF text was extracted automatically and may have reading-order or OCR errors; "
                "claims were not independently verified."
                if full_text
                else "Abstract-only analysis; methods and results were not verified against the "
                "full text."
            ),
        )


class TrendAnalystAgent:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend
        self.events: list[AgentEvent] = []

    def run(self, topic: str, trends: list[ThemeTrend]) -> list[TrendInsight]:
        fallback = _heuristic_insights(trends)
        if self.backend is None:
            self.events.append(
                AgentEvent(
                    "Trend Analyst Agent",
                    "heuristic",
                    "Converted deterministic trend statistics into evidence-linked observations.",
                )
            )
            return fallback
        try:
            candidates = self.backend.synthesize_trends(topic, trends)
            validated = _evidence_gate(candidates, trends)
            if not validated:
                raise ValueError("No model-generated insight passed the evidence gate")
            self.events.append(
                AgentEvent(
                    "Trend Analyst Agent",
                    "openai+evidence-gate",
                    f"Accepted {len(validated)} evidence-linked model observations.",
                )
            )
            return validated
        except Exception as exc:
            self.events.append(
                AgentEvent(
                    "Trend Analyst Agent",
                    "heuristic-fallback",
                    f"Model synthesis failed validation; used deterministic observations: {exc}",
                )
            )
            return fallback


def topic_terms(topic: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", topic.lower())
    return _unique_tokens(token for token in tokens if token not in STOPWORDS)[:10]


def topic_phrases(topic: str) -> list[str]:
    lowered = topic.lower().strip()
    terms = topic_terms(topic)
    if not terms:
        return []
    has_connector = re.search(r"\b(and|for|with|using|in|on)\b|[,;]", lowered) is not None
    if len(terms) <= 3 and not has_connector:
        return [" ".join(terms)]

    segments = re.split(r"\b(?:and|for|with|using|in|on)\b|[,;]", lowered)
    phrases: list[str] = []
    for segment in segments:
        segment_terms = topic_terms(segment)
        if segment_terms:
            phrases.append(" ".join(segment_terms[:3]))
    if len(phrases) == 1 and len(terms) >= 4:
        phrases = [" ".join(terms[:2]), terms[2], " ".join(terms[3:5])]
    return _unique_strings(phrases, limit=6, lowercase=True)


def default_themes(topic: str) -> tuple[ThemeDefinition, ...]:
    core = tuple(topic_terms(topic)[:6])
    return (
        ThemeDefinition("Topic core", core),
        ThemeDefinition(
            "Modeling and algorithms",
            (
                "model",
                "algorithm",
                "neural network",
                "transformer",
                "recurrent",
                "bayesian",
                "regression",
            ),
        ),
        ThemeDefinition(
            "Data and evaluation",
            ("dataset", "benchmark", "evaluation", "experiment", "empirical", "data"),
        ),
        ThemeDefinition(
            "Applications",
            ("application", "clinical", "biomedical", "healthcare", "biology", "drug"),
        ),
    )


def method_counts(analyses: list[PaperAnalysis]) -> Counter[str]:
    return Counter(method for analysis in analyses if analysis.relevant for method in analysis.methods)


def _heuristic_insights(trends: list[ThemeTrend]) -> list[TrendInsight]:
    insights: list[TrendInsight] = []
    for trend in trends:
        if len(trend.supporting_ids) < 2:
            continue
        if trend.direction == "emerging":
            claim = (
                f"Within this arXiv sample, abstracts associated with {trend.theme} appear in the "
                "recent window but not in the baseline window."
            )
        elif trend.direction == "increasing":
            claim = (
                f"Within this arXiv sample, the share of relevant abstracts associated with "
                f"{trend.theme} increased by {trend.change_percentage_points:.1f} percentage points."
            )
        elif trend.direction == "declining":
            claim = (
                f"Within this arXiv sample, the share of relevant abstracts associated with "
                f"{trend.theme} decreased by {abs(trend.change_percentage_points):.1f} percentage points."
            )
        else:
            claim = (
                f"Within this arXiv sample, {trend.theme} has no strong directional signal across "
                "the two windows."
            )
        confidence = "moderate" if len(trend.supporting_ids) >= 5 else "preliminary"
        insights.append(
            TrendInsight(
                theme=trend.theme,
                claim=claim,
                supporting_ids=trend.supporting_ids[:8],
                confidence=confidence,
            )
        )
    return insights[:4]


def _evidence_gate(
    candidates: list[dict[str, Any]], trends: list[ThemeTrend]
) -> list[TrendInsight]:
    by_theme = {trend.theme: trend for trend in trends}
    accepted: list[TrendInsight] = []
    for candidate in candidates[:6]:
        theme = str(candidate.get("theme", ""))
        trend = by_theme.get(theme)
        if trend is None:
            continue
        allowed_ids = set(trend.supporting_ids)
        ids = tuple(
            paper_id
            for paper_id in _unique_strings(candidate.get("supporting_ids", []), limit=8)
            if paper_id in allowed_ids
        )
        claim = str(candidate.get("claim", "")).strip()
        if len(ids) < 2 or not claim:
            continue
        confidence = str(candidate.get("confidence", "preliminary"))
        if confidence not in {"preliminary", "moderate"}:
            confidence = "preliminary"
        accepted.append(TrendInsight(theme, claim[:700], ids, confidence))
    return accepted[:4]


def _extractive_summary(abstract: str) -> str:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", abstract.strip())
        if len(sentence.strip().split()) >= 5
    ]
    if not sentences:
        return abstract[:500].strip()
    return " ".join(sentences[:2])[:700]


def _contains(text: str, term: str) -> bool:
    normalized = term.strip().lower()
    if not normalized:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None


def _query_unit(value: str) -> str:
    return f'all:"{value}"' if " " in value else f"all:{value}"


def _valid_arxiv_query(query: Any) -> bool:
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return False
    if "\n" in query or "http://" in query or "https://" in query:
        return False
    return re.fullmatch(r"[A-Za-z0-9_:\-+.()\"\s/*]+", query.strip()) is not None


def _unique_tokens(values: Any) -> list[str]:
    return _unique_strings(values, limit=20, lowercase=True)


def _unique_strings(values: Any, *, limit: int, lowercase: bool = False) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if lowercase:
            item = item.lower()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return result

