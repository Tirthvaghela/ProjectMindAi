"""LLM-generated NEW project concepts — the ideation half of the assistant.

Every other tool in nlp/chat_tools.py wraps something deterministic: a hybrid
search, a Mongo lookup, a template generator. This is the one place the model
is deliberately asked to invent something that doesn't exist in the catalogue
yet — a request for "new ideas" is a different job from "find a project,"
and conflating them is exactly why that request used to fall through to
search_projects (see nlp/ai_assistant.py's system message for the fix).

Every generated idea is run back through the EXISTING uniqueness checker
(nlp/recommend.py:check_uniqueness — the same engine /api/uniqueness and the
Idea Check page use) before being shown, so "this is original" is verified
against the real catalogue, not just asserted by the model that invented it.
The LLM is the creative brain; check_uniqueness is the knowledge/validation
step. Nothing here touches hybrid search or the recommendation engine.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from db.schema import DIFFICULTIES, DOMAINS
from nlp import recommend

log = logging.getLogger(__name__)

IDEA_COUNT_DEFAULT = 5
IDEA_COUNT_MAX = 6
# Below this originality score a generated idea is close enough to something
# that already exists to get one targeted regeneration pass instead of being
# shown as though it were novel.
MIN_ACCEPTABLE_ORIGINALITY = 55

_IDEATION_SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "You invent genuinely NEW student project concepts — not projects that already exist "
        "in any catalogue, and not a rephrasing of a common, overdone idea (to-do app, weather "
        "app, generic chatbot). Each idea must be a specific, buildable concept with a real point "
        "of differentiation. Respond with a JSON object only, no prose outside it, shaped exactly "
        'as: {"ideas": [{"name": str, "problem": str, "solution": str, "unique_point": str, '
        '"technologies": [str, ...], "domain": str, "difficulty": str, "duration_weeks": int}]}. '
        f"domain must be exactly one of: {', '.join(DOMAINS)}. "
        f"difficulty must be exactly one of: {', '.join(DIFFICULTIES)}. "
        "problem is 1-2 sentences on who struggles with what today. solution is 1-2 sentences on "
        "what the system does about it. unique_point is one sentence naming the SPECIFIC technique, "
        "angle, or constraint that makes this different from the obvious version of this idea — "
        "never just 'it uses AI' or 'it's more advanced'. technologies is 3-6 real, specific tools/"
        "frameworks/libraries genuinely appropriate to the idea. duration_weeks is a realistic "
        "solo-student estimate, typically 6-14."
    ),
}


def _build_prompt(
    topic: str, domain: Optional[str], difficulty: Optional[str], count: int, avoid: Optional[list[str]]
) -> str:
    parts = [f"Generate {count} new project ideas."]
    if topic:
        parts.append(f"Topic/theme: {topic}.")
    if domain:
        parts.append(f"Domain: {domain}.")
    if difficulty:
        parts.append(f"Difficulty: {difficulty}.")
    if avoid:
        parts.append(f"Avoid ideas overlapping with: {', '.join(avoid)}.")
    return " ".join(parts)


def _generate_raw(user_content: str, *, _retrying: bool = False) -> list[dict[str, Any]]:
    # Deferred import: breaks an import cycle (ai_assistant imports
    # chat_tools, chat_tools would need this module for the ideation tools).
    # By the time this function actually runs the app has finished starting,
    # so the cycle only matters at import time, not here.
    import config
    from nlp.ai_assistant import _create_completion

    completion = _create_completion(
        model=config.GROQ_MODEL,
        messages=[_IDEATION_SYSTEM_MESSAGE, {"role": "user", "content": user_content}],
        temperature=0.9,
        max_tokens=1800,
        response_format={"type": "json_object"},
    )
    # Malformed/empty provider response (no choices at all) is treated the
    # same as unparseable content below — not an IndexError.
    raw = completion.choices[0].message.content if completion.choices else None

    try:
        parsed = json.loads(raw)
        ideas = parsed.get("ideas")
    except (json.JSONDecodeError, TypeError):
        ideas = None

    if isinstance(ideas, list):
        # A syntactically valid response with a genuinely empty ideas list
        # (the model just had nothing to offer) is not malformed — return it
        # as-is rather than spending a retry on it.
        return ideas

    # Bad JSON, or JSON without a usable "ideas" list — worth exactly one
    # repair attempt (a fresh generation, not a re-parse of the same broken
    # text) before giving up; bounded so this can never loop.
    if _retrying:
        log.warning("Ideation response was still malformed after one retry")
        return []
    log.warning("Ideation response was not valid JSON — retrying once")
    return _generate_raw(user_content, _retrying=True)


def _validate(idea: dict[str, Any]) -> dict[str, Any]:
    """Runs one generated idea through the existing uniqueness checker and
    folds the result onto it — same engine /api/uniqueness and the Idea
    Check page use, so 'originality' means the same thing everywhere in
    this app, not a second definition invented for chat."""
    name = str(idea.get("name") or "").strip() or "Untitled idea"
    problem = str(idea.get("problem") or "").strip()
    solution = str(idea.get("solution") or "").strip()
    technologies = [t.strip() for t in (idea.get("technologies") or []) if isinstance(t, str) and t.strip()][:6]
    domain = idea.get("domain") if idea.get("domain") in DOMAINS else ""
    difficulty = idea.get("difficulty") if idea.get("difficulty") in DIFFICULTIES else "Intermediate"
    try:
        duration_weeks = max(1, min(int(idea.get("duration_weeks") or 8), 24))
    except (TypeError, ValueError):
        duration_weeks = 8

    description = f"{problem} {solution}".strip()
    result = recommend.check_uniqueness(name, description, domain=domain, technologies=technologies)

    return {
        "name": name,
        "problem": problem,
        "solution": solution,
        "unique_point": str(idea.get("unique_point") or "").strip(),
        "technologies": technologies,
        "domain": domain or (result["similar_projects"][0]["domain"] if result["similar_projects"] else ""),
        "difficulty": difficulty,
        "duration_weeks": duration_weeks,
        "originality_score": result["originality_score"],
        "is_unique": result["is_unique"],
        "similar_projects": result["similar_projects"][:3],
        "overlapping_concepts": result["overlapping_concepts"],
    }


def generate_ideas(
    topic: str = "",
    domain: Optional[str] = None,
    difficulty: Optional[str] = None,
    count: Optional[int] = None,
    avoid: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Generate `count` new project concepts, each validated against the
    existing catalogue via check_uniqueness. Any idea that lands below
    MIN_ACCEPTABLE_ORIGINALITY gets exactly one targeted regeneration pass
    naming what it was too close to; accepted either way afterward and
    always labelled with its real score, never silently retried forever."""
    n = max(1, min(int(count) if count else IDEA_COUNT_DEFAULT, IDEA_COUNT_MAX))
    domain = domain if domain in DOMAINS else None
    difficulty = difficulty if difficulty in DIFFICULTIES else None

    raw = _generate_raw(_build_prompt(topic, domain, difficulty, n, avoid))
    validated = [_validate(idea) for idea in raw[:n] if isinstance(idea, dict)]

    for i, idea in enumerate(validated):
        if idea["is_unique"] or idea["originality_score"] >= MIN_ACCEPTABLE_ORIGINALITY:
            continue
        closest = idea["similar_projects"][0]["title"] if idea["similar_projects"] else "an existing project"
        retry_prompt = (
            f"Generate 1 new project idea. Topic/theme: {topic or idea['domain'] or 'open'}. "
            f"A previous attempt (\"{idea['name']}\") was too similar to the existing catalogue "
            f"project \"{closest}\" — make this one meaningfully different in its core approach, "
            "not just reworded or renamed."
        )
        retried = _generate_raw(retry_prompt)
        if retried and isinstance(retried[0], dict):
            validated[i] = _validate(retried[0])

    for i, idea in enumerate(validated, start=1):
        idea["id"] = f"idea-{i}"
    return validated


def refine_idea(idea: dict[str, Any], instruction: str) -> dict[str, Any]:
    """Regenerate ONE existing (already-shown) idea against a follow-up
    instruction — 'make it more innovative', 'use a different tech stack' —
    then re-validate exactly like a freshly generated one. The model supplies
    the idea's current fields itself (there is no server-side idea store;
    see nlp/ai_assistant.py:_shown_ideas_note for how it keeps them in
    context), so this never depends on anything but this one call's inputs."""
    current = json.dumps(
        {
            "name": idea.get("name"),
            "problem": idea.get("problem"),
            "solution": idea.get("solution"),
            "unique_point": idea.get("unique_point"),
            "technologies": idea.get("technologies"),
            "domain": idea.get("domain"),
            "difficulty": idea.get("difficulty"),
            "duration_weeks": idea.get("duration_weeks"),
        }
    )
    prompt = (
        f"Here is an existing generated project idea: {current}. "
        f"The student wants this changed: \"{instruction}\". Produce exactly 1 refined idea in the "
        "same JSON schema — keep what already satisfies the request, change what's needed to "
        "genuinely satisfy it, not just reworded."
    )
    refined = _generate_raw(prompt)
    if refined and isinstance(refined[0], dict):
        result = _validate(refined[0])
    else:
        result = _validate(idea)
    result["id"] = idea.get("id") or "idea-1"
    return result
