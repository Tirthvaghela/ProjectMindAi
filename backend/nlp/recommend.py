"""Recommendation service — ties the retriever to the database.

Owns the single in-memory HybridRetriever for the process. Built once on first
use from MongoDB documents plus the on-disk embedding index, then reused.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import config
from db import client as db
from db.schema import DIFFICULTIES
from nlp import embeddings, generator, preprocess, timeline
from nlp.resume import detect_skills
from nlp.similarity import HybridRetriever, ScoredProject

log = logging.getLogger(__name__)

_retriever: Optional[HybridRetriever] = None
# Flask's dev server is threaded; without this two concurrent first-requests
# would each build a retriever and one would be silently discarded.
_lock = threading.Lock()

# Words that appear in so many skill phrases that matching on them alone means
# nothing. Used by skill_gap() to avoid crediting unrelated competencies.
GENERIC_SKILL_TOKENS = {
    "development", "developing", "design", "designing", "analysis", "analysing",
    "programming", "management", "engineering", "processing", "modelling",
    "modeling", "basic", "basics", "fundamental", "fundamentals", "advanced",
    "system", "systems", "application", "applications", "technique", "techniques",
    "tool", "tools", "concept", "concepts", "handling", "building",
}


def get_retriever() -> HybridRetriever:
    """Return the shared retriever, building it on first call."""
    global _retriever
    if _retriever is None:
        with _lock:
            if _retriever is None:
                _retriever = _build_retriever()
    return _retriever


def _build_retriever() -> HybridRetriever:
    matrix, ids = embeddings.load_index()

    documents = {
        doc["project_id"]: doc
        for doc in db.projects().find({}, {"_id": 0})
    }

    # The index is built from the DB, so a mismatch means the DB changed after
    # the last build. Drop the orphans rather than crash, but say so loudly.
    known = [pid for pid in ids if pid in documents]
    if len(known) != len(ids):
        missing = len(ids) - len(known)
        log.warning(
            "%d indexed project(s) are no longer in MongoDB. "
            "Rebuild with: python -m scripts.build_index",
            missing,
        )
        keep = [i for i, pid in enumerate(ids) if pid in documents]
        matrix = matrix[keep]
        ids = known

    # The other direction of drift: a project added (or re-seeded) in MongoDB
    # since the last index build has no embedding at all, so it can never
    # appear in search/similar/skill-gap results — silently, with nothing in
    # the response to say why. Detected here (once, at build time) rather
    # than on every request; this only ever logs a warning; it does not
    # rebuild anything itself, on purpose (see scripts/build_index.py — that
    # stays an explicit, operator-run step). /api/health surfaces the same
    # count comparison on every check so this isn't log-only.
    unindexed = [pid for pid in documents if pid not in known]
    if unindexed:
        log.warning(
            "%d MongoDB project(s) are not in the search index yet, so they "
            "will not appear in search results: %s%s. Rebuild with: "
            "python -m scripts.build_index",
            len(unindexed),
            ", ".join(unindexed[:5]),
            ", ..." if len(unindexed) > 5 else "",
        )

    log.info("Retriever ready with %d projects", len(ids))
    return HybridRetriever(matrix, ids, documents)


def warmup() -> None:
    """Build the retriever and load the embedding model now, not on a user's request.

    Both are lazily cached (get_retriever, embeddings.get_model), so without this
    whichever request happens to be first pays the full cold-start cost — index
    load, NLTK corpus downloads, BM25 build, and loading the sentence-transformer
    model — which together can take 30s+, well past the frontend's request timeout.
    Called once from create_app(); failures are logged, not raised, so a missing
    index or offline NLTK mirror degrades to the existing per-request error path
    instead of stopping the server from starting.
    """
    get_retriever()
    embeddings.encode_one("warmup")


def reset() -> None:
    """Drop cached state so the next call rebuilds. Used after re-seeding."""
    global _retriever
    with _lock:
        _retriever = None
    embeddings.load_index.cache_clear()


def build_profile(device_id: str) -> tuple[Optional[Any], dict[str, int]]:
    """Build a taste vector for one device from what it saved and searched.

    Returns (profile, signals). `profile` is a unit vector in the same space as
    the project embeddings, or None when the device has no usable history — in
    which case search behaves exactly as it did before personalisation existed.

    Two sources, deliberately weighted differently. Saving a project is an
    explicit endorsement; running a search is closer to idle curiosity, and a
    student who searched once for something they immediately rejected should
    not have that shape their results for the rest of the session.

    Favourited projects reuse vectors already in the index, so the only encode
    call is a single batched one for the recent queries.
    """
    import numpy as np

    retriever = get_retriever()
    signals = {"favorites": 0, "queries": 0}

    vectors: list[Any] = []
    weights: list[float] = []

    favorite_ids = [
        row["project_id"]
        for row in db.favorites().find({"device_id": device_id}, {"_id": 0, "project_id": 1})
    ]
    for pid in favorite_ids:
        index = retriever.position.get(pid)
        # A favourite whose project was deleted, or that predates the last
        # index rebuild, simply contributes nothing.
        if index is not None:
            vectors.append(retriever.matrix[index])
            weights.append(1.0)
            signals["favorites"] += 1

    recent = (
        db.history()
        .find({"device_id": device_id}, {"_id": 0, "query": 1})
        .sort("created_at", -1)
        .limit(config.PERSONALIZATION_MAX_QUERIES * 3)
    )
    seen: set[str] = set()
    queries: list[str] = []
    for row in recent:
        text = (row.get("query") or "").strip()
        key = text.lower()
        # De-duplicate: repeatedly running the same search should not let one
        # query dominate the profile purely by repetition.
        if text and key not in seen:
            seen.add(key)
            queries.append(text)
        if len(queries) >= config.PERSONALIZATION_MAX_QUERIES:
            break

    if queries:
        encoded = embeddings.encode(
            [preprocess.clean_for_embedding(q) for q in queries]
        )
        for vector in encoded:
            vectors.append(vector)
            weights.append(config.PERSONALIZATION_QUERY_WEIGHT)
            signals["queries"] += 1

    if not vectors:
        return None, signals

    profile = np.average(np.vstack(vectors), axis=0, weights=weights)
    norm = float(np.linalg.norm(profile))
    if norm < 1e-9:
        # Signals cancelled each other out exactly — no usable direction.
        return None, signals

    return (profile / norm).astype("float32"), signals


def search(
    query: str,
    filters: Optional[dict[str, Any]] = None,
    top_k: int = config.DEFAULT_TOP_K,
    profile: Optional[Any] = None,
) -> list[ScoredProject]:
    return get_retriever().search(query, filters=filters, top_k=top_k, profile=profile)


def similar(project_id: str, top_k: int = 5) -> list[ScoredProject]:
    return get_retriever().similar(project_id, top_k=top_k)


def explain(result: ScoredProject, query: str) -> str:
    """One-sentence, human-readable reason this project was recommended.

    Built from the two retrieval signals we already computed, so explainability
    costs nothing extra: the keyword half names the literal terms that matched,
    the dense half accounts for meaning-level similarity with no shared words.
    """
    doc = result.document

    if result.matched_terms:
        shown = ", ".join(result.matched_terms[:4])
        reason = f"matches your keywords ({shown})"
    else:
        reason = "is semantically close to your description"

    sentence = (
        f"This {doc.get('difficulty', '').lower()} {doc.get('domain', '')} project "
        f"{reason} and uses {', '.join(doc.get('technologies', [])[:3])}."
    )

    # Only claim personalisation when the affinity is actually strong. Every
    # result in a personalised search carries a personal_score, and saying "it
    # resembles what you saved" about a 0.1 cosine would be noise dressed up as
    # an explanation.
    if result.personal_score is not None and result.personal_score >= 0.35:
        sentence += " It also resembles projects you have saved or searched for."

    return sentence


def skill_gap_for_doc(doc: dict[str, Any], known_skills: list[str]) -> dict[str, Any]:
    """Compare a student's skills against a project-shaped doc's own
    "skills" field — the doc-based core `skill_gap()` (a catalogue project,
    looked up by project_id) and routes/ideas.py's idea-skill-gap endpoint
    (a synthetic doc from generator.idea_doc(), which mirrors technologies
    into skills — a generated idea has no separate skills taxonomy) both
    delegate to this, so the exact same matching logic backs both.

    Deliberately a set operation over lemmatised tokens rather than exact
    string equality, so "developing REST APIs" is credited against a required
    skill of "REST API development".
    """
    required = doc.get("skills", [])
    known_tokens: set[str] = set()
    for skill in known_skills:
        known_tokens |= preprocess.keyword_set(skill) - GENERIC_SKILL_TOKENS

    have, need = [], []
    for skill in required:
        # Subtract generic tokens before comparing. Without this, "React
        # development" credits "Smart contract development" on the shared word
        # "development" alone — measured: that pairing reported 25% readiness
        # for a student with no blockchain experience whatsoever.
        tokens = preprocess.keyword_set(skill) - GENERIC_SKILL_TOKENS

        # A skill made up entirely of generic words has nothing distinctive
        # left to match on, so treat it as not-yet-held rather than free credit.
        if tokens and tokens & known_tokens:
            have.append(skill)
        else:
            need.append(skill)

    total = len(required) or 1
    return {
        "project_id": doc.get("project_id"),
        "required_skills": required,
        "skills_you_have": have,
        "skills_to_learn": need,
        "readiness_percent": round(100 * len(have) / total, 1),
    }


def skill_gap(project_id: str, known_skills: list[str]) -> dict[str, Any]:
    """skill_gap_for_doc(), for a catalogue project looked up by project_id."""
    documents = get_retriever().documents
    doc = documents.get(project_id)
    if doc is None:
        raise KeyError(project_id)
    return skill_gap_for_doc(doc, known_skills)


# index gap between a student's stated experience level and a project's own
# difficulty -> a 0-100 fit score. Shared by chat_tools.recommend_decision and
# nlp/feasibility.py's analyze_feasibility so both ever report the exact same
# number for the same (project, experience_level) pair — not two
# implementations of the same judgement. Uses the same DIFFICULTIES ordering
# nlp/timeline.py's own experience multiplier uses, so the two signals never
# disagree about which direction is "ahead" vs "behind" — but it is its own
# small table, not a second copy of timeline's multiplier: that answers "how
# much faster/slower", this answers "how well does the level match".
_DIFFICULTY_FIT_BY_GAP = {0: 100, 1: 75}
_DIFFICULTY_FIT_FLOOR = 50


def difficulty_fit(project_difficulty: str, experience_level: Optional[str]) -> tuple[Optional[int], str]:
    """How well a student's stated experience level matches a project's own
    difficulty, as a 0-100 score — None (unavailable) when no
    experience_level was given, since that is genuinely unknown and must not
    be guessed."""
    if not experience_level:
        return None, "Experience level not given."
    try:
        project_idx = DIFFICULTIES.index(project_difficulty)
        student_idx = DIFFICULTIES.index(experience_level)
    except ValueError:
        return None, "Unrecognised difficulty level."

    gap = abs(student_idx - project_idx)
    score = _DIFFICULTY_FIT_BY_GAP.get(gap, _DIFFICULTY_FIT_FLOOR)

    if gap == 0:
        note = f"{experience_level} experience matches this project's {project_difficulty} difficulty."
    elif student_idx > project_idx:
        note = (
            f"{experience_level} experience is ahead of this project's {project_difficulty} "
            "difficulty — likely to feel easy."
        )
    else:
        note = (
            f"{experience_level} experience is behind this project's {project_difficulty} "
            "difficulty — likely to feel challenging."
        )
    return score, note


def _timeline_fit_score(predicted_weeks: float, max_duration_weeks: int) -> float:
    """0-100: how well a predicted duration fits inside a stated deadline.

    Meeting the deadline scores 100 regardless of margin (finishing early
    isn't "more correct"); overrunning it is penalised in proportion to how
    large the overrun is relative to the deadline itself, so a two-week
    slip on an 4-week plan hurts far more than the same slip on 20 weeks.
    """
    if predicted_weeks <= max_duration_weeks:
        return 100.0
    overrun_fraction = (predicted_weeks - max_duration_weeks) / max_duration_weeks
    return max(0.0, 100.0 - overrun_fraction * 100.0)


def _recommendation_reason(
    result: ScoredProject,
    skill_info: Optional[dict[str, Any]],
    timeline_fit: Optional[float],
    max_duration_weeks: Optional[int],
) -> str:
    """Extends explain()'s relevance sentence with skill/timeline clauses,
    every one of them read off a number this module already computed —
    never a fresh judgement, so the model-facing text can't drift from the
    scores it is describing."""
    sentence = explain(result, "")

    if skill_info is not None:
        readiness = skill_info["readiness_percent"]
        if readiness >= 70:
            sentence += f" You already have {readiness:g}% of the skills it needs."
        elif skill_info["skills_to_learn"]:
            preview = ", ".join(skill_info["skills_to_learn"][:2])
            sentence += f" You would need to learn {preview} first."

    if timeline_fit is not None and max_duration_weeks:
        if timeline_fit >= 100:
            sentence += f" It comfortably fits within your {max_duration_weeks}-week timeline."
        elif timeline_fit < 40:
            sentence += f" It's likely to run longer than your {max_duration_weeks}-week timeline."

    return sentence


def personalized_recommend(
    query: str = "",
    known_skills: Optional[list[str]] = None,
    technologies: Optional[list[str]] = None,
    domain: Optional[str] = None,
    difficulty: Optional[str] = None,
    max_duration_weeks: Optional[int] = None,
    team_size: int = 1,
    experience_level: Optional[str] = None,
    top_k: int = config.DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Multi-factor, personalized recommendation over the whole catalogue.

    The orchestration layer the other recommendation flavours (plain search,
    skill-gap, timeline, filters) fall out of as special cases: it reuses
    `search()` for candidate retrieval + filtering (same HybridRetriever,
    same dense/sparse fusion — no second ranking algorithm), `skill_gap()`
    for the have/need breakdown, and `timeline.predict()` for the completion
    estimate. Nothing here invents a score — every number traces back to one
    of those three existing functions, combined by a transparent, documented
    weighted average (config.RECOMMEND_*_WEIGHT).

    `known_skills`/`technologies`/`domain` feed the query text when the
    caller has no natural-language `query` of their own (the same trick
    /api/resume-suggest already uses: detected skills become the query), so
    "beginner NLP project matching Python, Flask" works with no free-text
    query at all.
    """
    known_skills = [s.strip() for s in (known_skills or []) if isinstance(s, str) and s.strip()]
    technologies = [t.strip() for t in (technologies or []) if isinstance(t, str) and t.strip()]

    effective_query = (query or "").strip()
    if not effective_query:
        parts = known_skills + technologies + ([domain] if domain else [])
        effective_query = ", ".join(parts)
    if not effective_query:
        return []

    filters: dict[str, Any] = {}
    if domain:
        filters["domain"] = domain
    if difficulty:
        filters["difficulty"] = difficulty
    if technologies:
        filters["technologies"] = technologies
    if max_duration_weeks:
        filters["max_duration_weeks"] = max_duration_weeks

    top_k = max(1, min(top_k, config.MAX_TOP_K))
    # A wider candidate pool than the final top_k, so skill/timeline fit can
    # re-order results beyond whatever plain relevance alone would surface —
    # otherwise a project ranked #12 on relevance but a perfect skill match
    # would never get the chance to out-rank #3.
    candidate_k = max(1, min(top_k * 4, config.MAX_TOP_K))

    candidates = search(effective_query, filters=filters or None, top_k=candidate_k)
    if not candidates:
        return []

    size = max(1, min(team_size or 1, 20))
    level = experience_level if experience_level in DIFFICULTIES else None
    tech_wanted = {t.lower() for t in technologies}

    recommendations: list[dict[str, Any]] = []
    for result in candidates:
        doc = result.document

        skill_info = skill_gap(result.project_id, known_skills) if known_skills else None
        estimate = timeline.predict(doc, team_size=size, experience_level=level)
        timeline_fit = (
            _timeline_fit_score(estimate["predicted_weeks"], max_duration_weeks)
            if max_duration_weeks
            else None
        )

        matching_factors: list[str] = []
        if domain and doc.get("domain") == domain:
            matching_factors.append(f"Domain match: {domain}")
        if difficulty and doc.get("difficulty") == difficulty:
            matching_factors.append(f"Difficulty match: {difficulty}")
        if tech_wanted:
            matched_tech = [t for t in doc.get("technologies", []) if t.lower() in tech_wanted]
            if matched_tech:
                matching_factors.append(f"Technology match: {', '.join(matched_tech)}")
        if result.matched_terms:
            matching_factors.append(f"Keyword match: {', '.join(result.matched_terms[:4])}")
        if skill_info and skill_info["skills_you_have"]:
            have = ", ".join(skill_info["skills_you_have"][:3])
            matching_factors.append(f"Skill match: you already have {have}")
        if timeline_fit is not None and timeline_fit >= 60:
            matching_factors.append(
                f"Fits your {max_duration_weeks}-week timeline "
                f"(~{estimate['predicted_weeks']:g} weeks estimated)"
            )

        # Transparent weighted average, renormalised over whichever signals
        # are actually present — identical pattern to
        # chat_tools.recommend_decision's overall_fit, just over the whole
        # catalogue instead of a caller-supplied shortlist.
        score_total = result.score * config.RECOMMEND_RELEVANCE_WEIGHT
        weight_total = config.RECOMMEND_RELEVANCE_WEIGHT
        if skill_info is not None:
            score_total += (skill_info["readiness_percent"] / 100) * config.RECOMMEND_SKILL_WEIGHT
            weight_total += config.RECOMMEND_SKILL_WEIGHT
        if timeline_fit is not None:
            score_total += (timeline_fit / 100) * config.RECOMMEND_TIMELINE_WEIGHT
            weight_total += config.RECOMMEND_TIMELINE_WEIGHT
        overall_score = round((score_total / weight_total) * 100, 1) if weight_total else 0.0

        payload = result.to_dict()
        payload["overall_score"] = overall_score
        payload["matching_factors"] = matching_factors
        payload["skill_gap"] = skill_info
        payload["timeline"] = {k: v for k, v in estimate.items() if k != "phases"}
        payload["recommendation_reason"] = _recommendation_reason(
            result, skill_info, timeline_fit, max_duration_weeks
        )
        recommendations.append(payload)

    recommendations.sort(key=lambda r: r["overall_score"], reverse=True)
    return recommendations[:top_k]


def check_uniqueness(
    title: str,
    description: str,
    threshold: Optional[float] = None,
    domain: str = "",
    technologies: Optional[list[str]] = None,
):
    """Find existing projects too similar to a proposed idea.

    Reuses the embedding index, so the uniqueness checker is essentially free.
    """
    threshold = config.UNIQUENESS_THRESHOLD if threshold is None else threshold
    retriever = get_retriever()

    text = preprocess.clean_for_embedding(f"{title}. {description}")
    vector = embeddings.encode_one(text)
    scores = embeddings.cosine_scores(vector, retriever.matrix)

    ranked = [
        {
            "project_id": retriever.ids[i],
            "title": retriever.documents[retriever.ids[i]].get("title"),
            "similarity": round(float(scores[i]), 4),
        }
        for i in range(len(retriever.ids))
    ]
    ranked.sort(key=lambda m: m["similarity"], reverse=True)
    top = ranked[:5]

    # Enrich with real catalogue fields already sitting in memory, so the
    # frontend can render a full project card without a second lookup —
    # nothing here is invented, it's the same documents the score came from.
    for match in top:
        doc = retriever.documents.get(match["project_id"], {})
        match["domain"] = doc.get("domain", "")
        match["difficulty"] = doc.get("difficulty", "")
        match["duration_weeks"] = doc.get("duration_weeks")
        match["technologies"] = doc.get("technologies", [])
        match["description"] = doc.get("description", "")
        # Three-tier read of the same similarity number, reusing the two
        # thresholds this module already has rather than inventing new
        # breakpoints: DUPLICATE_THRESHOLD is the same bar the dataset
        # deduplicator uses for "basically the same project", `threshold`
        # (UNIQUENESS_THRESHOLD by default) is the existing is_unique cutoff.
        if match["similarity"] >= config.DUPLICATE_THRESHOLD:
            match["similarity_level"] = "high"
        elif match["similarity"] >= threshold:
            match["similarity_level"] = "moderate"
        else:
            match["similarity_level"] = "low"

    highest_similarity = round(float(scores.max()), 4) if scores.size else 0.0
    is_unique = highest_similarity < threshold
    # closest_matches keeps its original, narrower meaning — only the
    # matches actually flagged as basically-a-duplicate — since the existing
    # About-page checker already renders it that way. `top` (below) is the
    # unconditional "here's what's closest regardless of the flag" list the
    # new richer checker needs, since a 60-70% match is still worth showing
    # even when it's not similar enough to call the idea unoriginal.
    closest_matches = [m for m in top if m["similarity"] >= threshold]

    # "Overlapping concepts" reuses the exact vocabulary-matching detect_skills()
    # already does for résumé matching, just against the idea's own text instead
    # of a résumé — so every overlap named here is a real technology/skill both
    # the idea and a close match mention, never guessed.
    vocabulary = set()
    for doc in retriever.documents.values():
        vocabulary.update(doc.get("technologies", []))
        vocabulary.update(doc.get("skills", []))
    idea_terms = set(detect_skills(text, sorted(vocabulary)))

    overlapping: list[str] = []
    seen_overlap: set[str] = set()
    for match in top[:3]:
        doc = retriever.documents.get(match["project_id"], {})
        project_terms = set(doc.get("technologies", [])) | set(doc.get("skills", []))
        for term in idea_terms & project_terms:
            key = term.lower()
            if key not in seen_overlap:
                seen_overlap.add(key)
                overlapping.append(term)

    suggestions: list[str] = []
    if top:
        top_match = top[0]
        if is_unique:
            suggestions.append(
                f"Your idea looks fairly distinct — the closest catalogue project, "
                f"\"{top_match['title']}\", is only {round(top_match['similarity'] * 100)}% similar."
            )
        else:
            if overlapping:
                suggestions.append(
                    f"Your idea overlaps with \"{top_match['title']}\" on {', '.join(overlapping[:3])} — "
                    "consider a different technology approach to stand apart."
                )
            suggestions.append(
                f"This is close to {len(closest_matches)} existing project(s) in "
                f"{top_match.get('domain') or 'this area'}; try narrowing the target users "
                "(a specific industry, age group, or team size) or the problem context "
                "(a particular workflow or constraint) the existing project doesn't address."
            )
            # Grounded cross-domain suggestion: only offered when a genuinely
            # different domain shows up among the closest matches themselves —
            # never a domain invented outside db.schema.DOMAINS.
            other_domains = [
                m.get("domain")
                for m in top[1:3]
                if m.get("domain") and m.get("domain") != top_match.get("domain")
            ]
            if other_domains:
                suggestions.append(
                    f"Combining {top_match.get('domain') or 'this domain'} with "
                    f"{other_domains[0]} is a real differentiator — none of the closest "
                    "matches do both."
                )
    else:
        suggestions.append("The catalogue has no projects to compare against yet.")

    # A first-draft "how to start" plan for the idea itself, built the same
    # way an existing project's roadmap is (nlp/generator.py:roadmap_for) —
    # template-based on domain, not model-generated, so nothing here is
    # invented beyond the domain's standard phase/module breakdown. The idea
    # has no duration_weeks of its own (it isn't in the catalogue), so the
    # closest catalogue match stands in as a realistic estimate; both the
    # domain and the duration are flagged as estimates when not user-given,
    # so the frontend can be honest about which numbers are guesses.
    domain_given = (domain or "").strip()
    domain_used = domain_given or (top[0].get("domain") if top else "") or ""
    duration_used = (top[0].get("duration_weeks") if top else None) or 8
    tech_used = [t for t in (technologies or []) if t] or (top[0].get("technologies") if top else []) or []
    profile = generator.domain_profile(domain_used)
    getting_started = {
        "domain": domain_used,
        "domain_is_estimate": not bool(domain_given),
        "estimated_weeks": duration_used,
        "technologies": tech_used,
        "phases": generator.phase_plan(duration_used, domain_used),
        "modules": profile["modules"],
    }

    return {
        "is_unique": is_unique,
        "threshold": threshold,
        "closest_matches": closest_matches,
        "similar_projects": top,
        "highest_similarity": highest_similarity,
        "originality_score": round((1 - highest_similarity) * 100),
        "overlapping_concepts": overlapping,
        "suggestions": suggestions,
        "getting_started": getting_started,
    }
