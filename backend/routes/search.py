"""Search, recommendation and analysis endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, request

import config
from db import client as db
from db.schema import DIFFICULTIES, DOMAINS
from extensions import limiter
from nlp import recommend
from nlp.learning_path import learning_path_for
from nlp.resume import UnreadableResume, detect_skills, extract_text
from nlp.team_builder import suggest_roles
from nlp.timeline import predict as predict_timeline
from routes.helpers import (
    ApiError,
    current_user,
    device_id,
    get_int,
    json_body,
    ok,
    parse_filters,
    validated_max_duration,
    top_k_from,
)

log = logging.getLogger(__name__)

bp = Blueprint("search", __name__, url_prefix="/api")


@bp.post("/search")
@limiter.limit("30 per minute")
def search():
    """Semantic + keyword search over the project corpus.

    Body: {query, domain?, difficulty?, technologies?, max_duration_weeks?,
           top_k?, device_id?}
    """
    body = json_body()
    query = (body.get("query") or "").strip()
    if not query:
        raise ApiError("'query' is required and cannot be empty.", status=400)
    if len(query) > 500:
        raise ApiError("'query' must be 500 characters or fewer.", status=400)

    validated_max_duration(body)  # an unusable deadline is a 400, never silently dropped
    filters = parse_filters(body)
    top_k = top_k_from(body)
    caller = device_id(required=False)

    # Personalisation is on by default for a device that has history, and the
    # client can turn it off per request. Building the profile must never cost
    # the user their results, so a failure here degrades to a plain search.
    wants_personal = body.get("personalize", True) is not False
    profile, signals = None, {"favorites": 0, "queries": 0}
    if caller and wants_personal and config.PERSONALIZATION_WEIGHT > 0:
        try:
            profile, signals = recommend.build_profile(caller)
        except Exception:  # noqa: BLE001
            log.exception("Failed to build personalisation profile")

    results = recommend.search(query, filters=filters, top_k=top_k, profile=profile)

    payload = []
    for result in results:
        item = result.to_dict()
        item["why_recommended"] = recommend.explain(result, query)
        payload.append(item)

    # Log the search for the history feature. Never let this break the
    # response — a failed analytics write must not cost the user their results.
    if caller:
        try:
            _record_history(caller, query, filters, len(payload))
        except Exception:  # noqa: BLE001
            log.exception("Failed to record search history")

    return ok(
        payload,
        query=query,
        filters=filters,
        count=len(payload),
        weights={"dense": config.DENSE_WEIGHT, "sparse": config.SPARSE_WEIGHT},
        personalization={
            "applied": profile is not None,
            "weight": config.PERSONALIZATION_WEIGHT if profile is not None else 0.0,
            "signals": signals,
        },
        excluded_unknown_duration=_unknown_duration_exclusions(filters),
    )


def _record_history(caller: str, query: str, filters: dict, result_count: int) -> None:
    db.history().insert_one(
        {
            "device_id": caller,
            "query": query,
            "filters": filters,
            "result_count": result_count,
            "created_at": datetime.now(timezone.utc),
        }
    )

    # Keep only the most recent N per device so the collection cannot grow
    # without bound from a single user hammering search.
    excess = (
        db.history().count_documents({"device_id": caller})
        - config.MAX_HISTORY_PER_DEVICE
    )
    if excess > 0:
        old = (
            db.history()
            .find({"device_id": caller}, {"_id": 1})
            .sort("created_at", 1)
            .limit(excess)
        )
        db.history().delete_many({"_id": {"$in": [d["_id"] for d in old]}})


def _unknown_duration_exclusions(filters: dict) -> int | None:
    """How many projects a deadline filter left out only because their duration
    is unknown — None when no deadline was applied, so the field only appears
    when it means something."""
    if not filters.get("max_duration_weeks"):
        return None
    return recommend.unknown_duration_count(filters)


def _profile_context(explicit_skills: int, requested_level):
    """(context for recommend, personalization report) for a use_profile request.

    The report is always returned so the UI can say what happened; the context
    is None unless a signed-in account has a profile with something usable.
    """
    from profiles import personalization, service

    user = current_user(required=False)
    if user is None:
        return None, {"requested": True, "applied": False, "reason": "sign_in_required"}
    profile = service.get_profile(user["user_id"])
    context = personalization.build_context(profile)
    if not context["usable"]:
        reason = "no_profile" if profile["completion"]["status"] == "not_started" else "nothing_usable"
        return None, {"requested": True, "applied": False, "reason": reason, "profile_status": profile["completion"]["status"]}
    source = "request" if requested_level else ("profile_skill_levels" if context["experience_level"] else "none")
    report = {
        "requested": True,
        "applied": True,
        "reason": "applied",
        "profile_status": profile["completion"]["status"],
        **personalization.summary(context, explicit_skills, source),
    }
    if requested_level:
        report["experience_level"] = requested_level
    return context, report


@bp.post("/recommend")
@limiter.limit("30 per minute")
def personalized_recommend():
    """Multi-factor personalized recommendation.

    Orchestrates the same building blocks /api/search, /api/skill-gap and
    /api/timeline-predict expose individually — hybrid retrieval + filters,
    skill-gap, timeline fit — into one ranked, explained list. See
    nlp/recommend.py:personalized_recommend for the scoring.

    Body: {query?, known_skills?, technologies?, domain?, difficulty?,
           max_duration_weeks?, team_size?, experience_level?, top_k?,
           use_profile?}
    At least one of query/known_skills/domain/difficulty/technologies/
    max_duration_weeks must be given — otherwise there is nothing to rank
    against. (With use_profile, usable signals in the caller's saved profile
    also count.)

    `use_profile: true` folds the signed-in account's saved learner profile
    into the ranking (profiles/personalization.py). It is opt-in so every
    existing caller is unchanged; signed out, or with nothing usable saved, the
    request is answered exactly as without it and `personalization` says why.
    The profile is always the one the auth token resolves to.
    """
    body = json_body()
    query = (body.get("query") or "").strip()
    if len(query) > 500:
        raise ApiError("'query' must be 500 characters or fewer.", status=400)

    known_skills = body.get("known_skills") or []
    if not isinstance(known_skills, list) or not all(isinstance(s, str) for s in known_skills):
        raise ApiError("'known_skills' must be a list of strings.", status=400)
    known_skills = [s.strip() for s in known_skills if s.strip()]

    validated_max_duration(body)  # 400 on an unusable deadline instead of ignoring it

    use_profile = body.get("use_profile", False)
    if not isinstance(use_profile, bool):
        raise ApiError("'use_profile' must be true or false.", status=400)
    profile_context, personalization = None, None
    if use_profile:
        profile_context, personalization = _profile_context(len(known_skills), body.get("experience_level"))

    filters = parse_filters(body)
    if not query and not known_skills and not filters and not profile_context:
        raise ApiError(
            "Provide at least a 'query', 'known_skills', or a filter "
            "(domain/difficulty/technologies/max_duration_weeks).",
            status=400,
        )

    team_size = get_int(body, "team_size", 1, 1, 20)

    experience_level = body.get("experience_level") or None
    if experience_level is not None and experience_level not in DIFFICULTIES:
        raise ApiError(f"'experience_level' must be one of {', '.join(DIFFICULTIES)}.", status=400)

    top_k = top_k_from(body)

    results = recommend.personalized_recommend(
        query=query,
        known_skills=known_skills,
        technologies=filters.get("technologies"),
        domain=filters.get("domain"),
        difficulty=filters.get("difficulty"),
        max_duration_weeks=filters.get("max_duration_weeks"),
        team_size=team_size,
        experience_level=experience_level,
        top_k=top_k,
        profile_context=profile_context,
    )

    # Only when a deadline is set can "nothing fits" be explained with real
    # numbers; otherwise an empty list just means nothing matched the query.
    diagnostics = None
    if not results and filters.get("max_duration_weeks"):
        diagnostics = recommend.explain_empty(filters["max_duration_weeks"], team_size, experience_level)

    return ok(
        results,
        query=query,
        known_skills=known_skills,
        filters=filters,
        team_size=team_size,
        experience_level=experience_level,
        count=len(results),
        diagnostics=diagnostics,
        excluded_unknown_duration=_unknown_duration_exclusions(filters),
        **({"personalization": personalization} if personalization is not None else {}),
    )


@bp.get("/similar/<project_id>")
def similar(project_id: str):
    """Projects most like the given one (pure dense similarity)."""
    top_k = top_k_from(request.args.to_dict())
    results = recommend.similar(project_id, top_k=top_k)

    if not results and project_id not in recommend.get_retriever().documents:
        raise ApiError(f"No project with id '{project_id}'.", status=404)

    return ok([r.to_dict() for r in results], project_id=project_id, count=len(results))


@bp.get("/skill-gap/me")
@limiter.limit("60 per minute")
def personal_skill_gap():
    """The signed-in account's own saved profile against one catalogue project.

    Query: ?project_id=<id>. The profile is always the one the auth token
    resolves to - there is no user parameter. Deterministic, no LLM. See
    nlp/personal_skill_gap.py for the classification and priority rules, which
    every response restates under `rules`.
    """
    from nlp.personal_skill_gap import analyse
    from profiles import service as profile_service

    user = current_user()
    project_id = request.args.get("project_id", "")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ApiError("'project_id' is required.", status=400)
    project_id = project_id.strip()
    if len(project_id) > 64:
        raise ApiError("'project_id' is too long.", status=400)

    doc = recommend.get_retriever().documents.get(project_id)
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)
    return ok(analyse(doc, profile_service.get_profile(user["user_id"])))


@bp.post("/skill-gap")
def skill_gap():
    """Compare a student's skills against a project's requirements."""
    body = json_body()
    project_id = (body.get("project_id") or "").strip()
    skills = body.get("skills") or []

    if not project_id:
        raise ApiError("'project_id' is required.", status=400)
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise ApiError("'skills' must be a list of strings.", status=400)

    try:
        return ok(recommend.skill_gap(project_id, skills))
    except KeyError:
        raise ApiError(f"No project with id '{project_id}'.", status=404) from None


@bp.post("/uniqueness")
@limiter.limit("20 per minute")
def uniqueness():
    """Check a proposed project idea against the existing corpus."""
    body = json_body()
    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    domain = (body.get("domain") or "").strip()
    technologies = [t.strip() for t in (body.get("technologies") or []) if t and t.strip()]

    if not title and not description:
        raise ApiError("Provide at least a 'title' or 'description'.", status=400)

    return ok(recommend.check_uniqueness(title, description, domain=domain, technologies=technologies))


@bp.post("/team-builder")
# Unauthenticated, deterministic, but takes an unbounded-looking members list
# and no rate limit at all — matches search/recommend's own limit above since
# it's the same shape of route (unauthenticated POST in this blueprint).
@limiter.limit("30 per minute")
def team_builder():
    """Suggest a project role for each team member, given their skills.

    Body: {project_id, members: [{name?, skills: [str]}]}
    """
    body = json_body()
    project_id = (body.get("project_id") or "").strip()
    members = body.get("members") or []

    if not project_id:
        raise ApiError("'project_id' is required.", status=400)
    if not isinstance(members, list) or not members:
        raise ApiError("'members' must be a non-empty list.", status=400)
    if len(members) > 20:
        raise ApiError("'members' must be 20 or fewer.", status=400)
    for member in members:
        if not isinstance(member, dict) or not isinstance(member.get("skills", []), list):
            raise ApiError("Each member must be an object with a 'skills' list.", status=400)

    doc = db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)

    return ok(suggest_roles(doc, members))


@bp.post("/learning-path")
def learning_path():
    """Resource links for a list of skills — typically the skills_to_learn from /api/skill-gap."""
    body = json_body()
    skills = body.get("skills") or []

    if not isinstance(skills, list) or not skills or not all(isinstance(s, str) for s in skills):
        raise ApiError("'skills' must be a non-empty list of strings.", status=400)
    if len(skills) > 20:
        raise ApiError("'skills' must be 20 or fewer.", status=400)

    return ok(learning_path_for(skills))


@bp.post("/timeline-predict")
def timeline_predict():
    """Personalised completion-time estimate for a project.

    Body: {project_id, team_size?: int, experience_level?: Beginner|Intermediate|Advanced}
    """
    body = json_body()
    project_id = (body.get("project_id") or "").strip()
    if not project_id:
        raise ApiError("'project_id' is required.", status=400)

    team_size = get_int(body, "team_size", 1, 1, 20)

    experience_level = body.get("experience_level") or None
    if experience_level is not None and experience_level not in DIFFICULTIES:
        raise ApiError(f"'experience_level' must be one of {', '.join(DIFFICULTIES)}.", status=400)

    doc = db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)

    return ok(predict_timeline(doc, team_size=team_size, experience_level=experience_level))


@bp.post("/resume-suggest")
@limiter.limit("10 per minute")
def resume_suggest():
    """Project matches for an uploaded résumé, or pasted résumé text.

    Multipart form with a 'resume' file (PDF/DOCX/TXT), OR a JSON body with
    'text'. Skills detected in the résumé drive the same multi-factor
    personalized_recommend() /api/recommend already exposes — not a second
    ranking algorithm — so a résumé match already blends skill fit into the
    ranking, not just plain relevance.
    """
    text = ""
    upload = request.files.get("resume")
    if upload and upload.filename:
        try:
            text = extract_text(upload)
        except UnreadableResume as error:
            raise ApiError(
                f"Could not read that résumé: {error}. Try a PDF with a text layer, a DOCX, or paste the text instead.",
                status=400,
            ) from None
    elif request.is_json:
        text = ((request.get_json(silent=True) or {}).get("text") or "").strip()

    if not text.strip():
        raise ApiError("Upload a résumé file (PDF/DOCX/TXT) or provide 'text'.", status=400)

    # Domain names are real catalogue values too (every project's own
    # `domain` is one of these), so a résumé mentioning "Machine Learning" or
    # "NLP" experience is recognised the same as a résumé naming a concrete
    # technology, without inventing a second vocabulary.
    vocabulary = (
        list(db.projects().distinct("technologies"))
        + list(db.projects().distinct("skills"))
        + list(DOMAINS)
    )
    detected = detect_skills(text, vocabulary)

    # A résumé with none of the dataset's known terms still deserves a
    # result — fall back to the raw text itself as the query rather than
    # returning nothing.
    query = ", ".join(detected) if detected else text[:500]
    top_k = top_k_from(request.args.to_dict())

    results = recommend.personalized_recommend(query=query, known_skills=detected, top_k=top_k)
    payload = []
    for result in results:
        item = dict(result)
        skill_info = item.pop("skill_gap", None) or {}
        item["why_recommended"] = item.pop("recommendation_reason", "")
        item["skills_you_have"] = skill_info.get("skills_you_have", [])
        item["skills_to_learn"] = skill_info.get("skills_to_learn", [])
        item["readiness_percent"] = skill_info.get("readiness_percent")
        payload.append(item)

    return ok(payload, detected_skills=detected, query_used=query, count=len(payload))
