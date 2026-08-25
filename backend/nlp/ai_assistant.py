"""AI chat assistant — the one LLM-backed feature in this codebase.

Everything else here (search, skill_gap, check_uniqueness, generator,
team_builder, timeline, learning_path) is a deterministic function over the
project's own fields, kept that way deliberately: no external cost, no API
key required to run the app, nothing to hallucinate. Free-form "ask me
anything about this project" genuinely needs open-ended generation, so it is
the one place that trade-off is made — gated behind an optional GROQ_API_KEY,
with the rest of the app fully functional when it's unset.

Two entry points share the same client and history handling:
- `reply()` — grounded in one project's fields (the "Ask about this project"
  widget on ProjectDetail). No tools: it already has the one project's real
  data in its system message, so there is nothing to retrieve.
- `general_reply()` — the conversational assistant behind the Dashboard chat,
  with no single project fixed in scope. It is RAG-grounded via tool calling
  (see nlp/chat_tools.py): every tool wraps something that already exists
  (hybrid search, a Mongo lookup, skill_gap/timeline/learning_path/generator),
  not a second implementation of any of them. A conversation can also carry a
  `selected_project_id` (set via the select_project tool or the frontend's
  "Select Project" button) — when present, it's injected as context so
  follow-ups ("how should I build the backend?") are grounded in that project
  without the student having to name it again.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import time
from functools import lru_cache
from typing import Any, Optional

import config
from nlp import chat_tools

log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 2000
# Bounds the tool-calling loop for one turn — a handful of rounds is enough
# for "search, then look up one result's details, then roadmap it", and a
# hard cap guarantees the loop terminates even if the model keeps calling
# tools instead of answering.
MAX_TOOL_ROUNDS = 4

_SYSTEM_TEMPLATE = """You are a project mentor helping a student build the academic project below. \
Answer questions about how to build it, which technologies to use, architecture and design \
decisions, debugging approaches, and related concepts. Be concise and practical — a few short \
paragraphs or a short list, not an essay. Ground every answer in the project's actual details \
below; if something the student asks about isn't covered by them (a dataset, a deployment target, \
a specific feature), say plainly that it isn't specified rather than inventing a plausible-sounding \
answer. You provide guidance and plans only — never claim to have implemented, written, tested, or \
changed this project's actual code. If the student asks something unrelated to building this \
project, gently steer the conversation back to it.

PROJECT: {title}
DOMAIN: {domain}
DIFFICULTY: {difficulty}
DESCRIPTION: {description}
TECHNOLOGIES: {technologies}
SKILLS INVOLVED: {skills}
"""

_GENERAL_SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "You are the ProjectMind AI assistant, embedded in a student project-recommendation "
        "platform. You help a student discover, compare, select, and plan how to build a "
        "project.\n\n"
        "SCOPE — you are a project-recommendation and build-mentorship assistant, not a "
        "general-purpose chatbot. In scope: catalogue/generated projects, their architecture/"
        "technologies, skills and learning paths, team size/roles for BUILDING the project, "
        "timelines, and originality checks. Out of scope: chit-chat about the student's "
        "family, friends, relationships, or personal life, general life advice, news, "
        "entertainment, or anything else unconnected to a project — decline in one short "
        "sentence and ask what project or idea they'd like help with, never call a tool for "
        "it. A question about team size, splitting roles/tasks, or who should build which part "
        "of the project IS in scope.\n\n"
        "Every tool wraps ProjectMind's real catalogue/generators — never invent a project, "
        "technology, skill, roadmap, or synopsis; every fact you state must come from a tool "
        "result. Each tool's own description (in its schema) explains exactly when to use it "
        "vs. its neighbours — read those rather than guessing, especially search_projects vs. "
        "generate_project_ideas, and the catalogue tools (generate_roadmap, predict_timeline, "
        "generate_milestones) vs. their generate_idea_* mirrors for a GENERATED idea (no "
        "project_id). select_project/select_idea are mutually exclusive — selecting one clears "
        "the other. Resolve simple requests in one tool round when the required context/data is "
        "already available — do not call another tool unnecessarily.\n\n"
        "DISCOVERY vs IDEATION — the distinction that matters most. The student is either "
        "asking to find something that already exists (DISCOVERY -> search_projects) or asking "
        "you to invent something new (IDEATION -> generate_project_ideas). 'Give me NLP "
        "projects', 'find projects similar to X', 'recommend a project' are DISCOVERY. 'Give me "
        "NEW/innovative/original ideas', 'what can I build', 'I want something unique' are "
        "IDEATION — never search_projects for these; a plain request with no novelty language "
        "defaults to DISCOVERY. A generated idea is never a catalogue project: never give it a "
        "project_id or call a catalogue tool (get_project_details, select_project, "
        "generate_roadmap, ...) on it — use the generate_idea_* versions — and always label it "
        "as an AI-generated idea, not something from the catalogue.\n\n"
        "CONTEXT NOTES — earlier assistant turns may carry a bracketed note you use silently, "
        "never quoting it to the student: '[Context — projects shown above...]' or "
        "'[...ideas shown above...]' lists each item's position/id/fields so you can resolve "
        "'the second one', 'the Python one', etc. to a real id — reuse an idea's exact fields "
        "(never invent new ones) for refine_project_idea/generate_idea_roadmap. '[Context — "
        "comparison shown above...]'/'[...decision shown above...]' carry the same real difficulty/"
        "duration/technologies/uniqueness (plus fit scores for a decision) — resolve a follow-up "
        "about that comparison/decision from these numbers instead of re-calling compare_projects/"
        "recommend_decision. '[Context — active project/idea: ...]' names the student's current "
        "build target (at most one of the two); an otherwise-ambiguous question ('how should I "
        "build the backend?') is about whichever is present. '[Context — résumé skills already "
        "on file...]' lists skills "
        "from an uploaded résumé — pass it straight through as known_skills wherever needed "
        "instead of asking the student to re-list it.\n\n"
        "Always fire search_projects/generate_project_ideas immediately on a first find/recommend "
        "request, shown as cards — never ask what the student already knows before that first "
        "search just to decide what to look for; "
        "known_skills is optional ranking context, not a prerequisite, and every card already "
        "carries its own select_project option. Only AFTER the student has actually selected a "
        "project or idea and planning gets specific, get to know them before going further — "
        "ask what they already know, grouped by category (Programming Languages, Frontend, "
        "Backend, Databases, AI / ML, Tools), briefly and naturally, not a form dump. Use the "
        "answer as known_skills for check_skill_gap rather than guessing or calling it empty.\n\n"
        "When the student proposes a specific technology, judge it against that project's real "
        "technologies/domain/skills rather than just agreeing — if it's a poor fit, say so "
        "plainly with the concrete reason and recommend a real alternative actually in the "
        "project's own stack, never invented.\n\n"
        "Once a project or idea is active, you are its build mentor. "
        "Architecture/backend/implementation questions must be adapted to that specific "
        "project's real domain, technologies, and skills — never one generic shape reused for "
        "every project (a CLI or IoT project may have no frontend layer, for instance). Prefer "
        "the roadmap tools' real objective/tasks/technologies/expected_output per phase over "
        "inventing your own plan; for a follow-up about one phase already shown, call that same "
        "roadmap tool again (a free, deterministic lookup) rather than trusting your own earlier "
        "summary. For a prioritisation question under a real constraint ('3 months, what should "
        "I prioritise'), reason from real signals — duration_weeks, predict_timeline, an "
        "already-computed skill gap, the roadmap's phase list — calling those tools if not "
        "already called, rather than improvising; the domain's core phase is the last thing to "
        "cut, polish/optional layers first. If no project or idea is active and the question has "
        "no other referent, ask which project or idea before answering — never guess. If "
        "something genuinely isn't in the project's data, say plainly it isn't specified rather "
        "than inventing an answer. You give guidance and plans only — never claim to have "
        "implemented, written, tested, or changed the student's actual code, backend, or "
        "database.\n\n"
        "FEASIBILITY — 'can I build this', 'how difficult/realistic is this', 'what are the "
        "risks' about ONE project/idea call analyze_project_feasibility/analyze_idea_feasibility "
        "immediately (catalogue vs generated idea, same pairing as the timeline tools) instead of "
        "check_skill_gap/predict_timeline separately — it already combines skill fit, timeline "
        "fit, difficulty fit, technical complexity, and team-size fit into one score, plus real "
        "infrastructure/dataset guidance. Call it even with no known_skills/team_size/experience_level yet — same as "
        "search_projects, those stay optional; Skill Fit/Difficulty Fit just come back unavailable "
        "rather than blocking the analysis. Still use recommend_decision (not this) for 'which "
        "should I choose' across several projects.\n\n"
        "SCOPE — 'what should this include', 'MVP', 'what should I remove/cut', or 'I only have N "
        "weeks' (shorter than the project's own duration) about ONE project/idea calls analyze_scope "
        "(project_id for a catalogue project, name+its context fields for a generated idea — one "
        "tool either way). Present remove/keep exactly as returned; never remove anything yourself.\n\n"
        "RESOURCES — 'how many people do I need', 'what technologies do I need', 'can I build this "
        "with free tools', or team/tech/cost questions about ONE project/idea calls "
        "estimate_project_resources (project_id or name+context, one tool either way). Every cost "
        "it returns is an estimate/range — present it as such, never as an exact price.\n\n"
        "Be concise and practical — a few short paragraphs or a short list, not an essay. Use "
        "Markdown where it aids clarity, including tables for genuinely tabular data. When a "
        "tool call produces cards/tables shown separately to the student (search_projects, "
        "compare_projects, check_skill_gap, predict_timeline, generate_milestones, "
        "get_learning_path, generate_project_ideas, refine_project_idea, generate_idea_timeline, "
        "generate_idea_milestones, analyze_project_feasibility, analyze_idea_feasibility, "
        "analyze_scope, estimate_project_resources), keep your own reply to a sentence or two of "
        "framing — do not "
        "re-list what's already shown. generate_roadmap/generate_synopsis/generate_idea_roadmap "
        "have no such block — your own Markdown (headings, a numbered phase list, tables) is "
        "what carries the phases/tasks/sections, using only fields the tool actually returned. "
        "For generate_project_ideas, your framing should make clear these are new AI-generated "
        "concepts, not existing catalogue projects."
    ),
}


def _shown_projects_note(blocks: list[dict[str, Any]]) -> str:
    """Compact, model-facing summary of project_recommendations blocks on one
    stored assistant turn — ordinal position, id, title, difficulty and top
    technologies, which is enough for the model to resolve 'the second one'
    or 'the Python one' itself on the next turn without a bespoke resolver."""
    lines = []
    for block in blocks or []:
        if block.get("type") != "project_recommendations":
            continue
        for i, project in enumerate(block.get("projects") or [], start=1):
            tech = ", ".join((project.get("technologies") or [])[:3])
            detail = project.get("difficulty", "")
            if tech:
                detail = f"{detail}, {tech}" if detail else tech
            suffix = f" ({detail})" if detail else ""
            lines.append(f"{i}. {project.get('project_id', '')} \"{project.get('title', '')}\"{suffix}")
    if not lines:
        return ""
    return "\n\n[Context — projects shown above, in order:\n" + "\n".join(lines) + "]"


# problem/solution/unique_point are free-form model prose and, unlike a
# project's technologies/domain/difficulty, have no natural length cap —
# five ideas' worth of all three, replayed on every later turn, is real,
# measured budget pressure against a tools-heavy model's tokens-per-minute
# limit (see _history_messages' docstring). Previewed the same way
# _active_project_note already previews a project's description, at a
# length still long enough for the model to ground a follow-up question or
# a refine_project_idea call in what the idea actually is.
_IDEA_NOTE_FIELD_PREVIEW_CHARS = 160


def _preview(text: Optional[str], limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;: ") + "…"


def _shown_ideas_note(blocks: list[dict[str, Any]]) -> str:
    """Compact, model-facing summary of generated_project_ideas blocks on one
    stored assistant turn — full enough (problem, solution, unique point,
    technologies, domain, difficulty, duration, originality) that a later
    refine_project_idea or generate_idea_roadmap call, or a plain follow-up
    question, never needs a server-side idea store: generated ideas are
    never written to Mongo, so this note is the only place their fields
    persist across turns, exactly mirroring _shown_projects_note above."""
    lines = []
    for block in blocks or []:
        if block.get("type") != "generated_project_ideas":
            continue
        for i, idea in enumerate(block.get("ideas") or [], start=1):
            tech = ", ".join(idea.get("technologies") or [])
            problem = _preview(idea.get("problem"), _IDEA_NOTE_FIELD_PREVIEW_CHARS)
            solution = _preview(idea.get("solution"), _IDEA_NOTE_FIELD_PREVIEW_CHARS)
            unique = _preview(idea.get("unique_point"), _IDEA_NOTE_FIELD_PREVIEW_CHARS)
            lines.append(
                f"{i}. id={idea.get('id')} \"{idea.get('name')}\" — "
                f"problem: {problem} | solution: {solution} | "
                f"unique: {unique} | tech: {tech} | "
                f"domain: {idea.get('domain')} | difficulty: {idea.get('difficulty')} | "
                f"duration: {idea.get('duration_weeks')}wk | originality: {idea.get('originality_score')}%"
            )
    if not lines:
        return ""
    return "\n\n[Context — generated ideas shown above, in order:\n" + "\n".join(lines) + "]"


def _shown_comparison_note(blocks: list[dict[str, Any]]) -> str:
    """Compact, model-facing summary of a comparison block on one stored
    assistant turn — the compare_projects mirror of _shown_projects_note
    above. Exists because, unlike project_recommendations/
    generated_project_ideas, a comparison's own data (technologies, skills,
    uniqueness_percent) was previously NOT replayed into later-turn history
    at all — only the model's own brief prose framing was (see the system
    prompt's "keep your own reply to a sentence or two of framing" rule),
    which live testing showed the model correctly declines to fully trust on
    a follow-up (e.g. 'which of those is easier?'), re-calling
    compare_projects to get grounded data again even when the answer was
    already derivable. This note gives the model the same kind of reliable,
    structured, explicitly-labelled context it already trusts for shown
    projects/ideas, so a simple follow-up can be answered from it directly —
    never removes the option to re-call compare_projects for anything this
    note doesn't cover (skills, full description, more projects, ...)."""
    lines = []
    for block in blocks or []:
        if block.get("type") != "comparison":
            continue
        for i, project in enumerate(block.get("projects") or [], start=1):
            tech = ", ".join((project.get("technologies") or [])[:3])
            lines.append(
                f"{i}. {project.get('project_id', '')} \"{project.get('title', '')}\" — "
                f"{project.get('difficulty', '')}, {project.get('duration_weeks')}wk, "
                f"tech: {tech}, uniqueness: {project.get('uniqueness_percent')}%"
            )
    if not lines:
        return ""
    return "\n\n[Context — comparison shown above, in order:\n" + "\n".join(lines) + "]"


def _shown_decision_note(blocks: list[dict[str, Any]]) -> str:
    """Compact, model-facing summary of a decision block on one stored
    assistant turn — the recommend_decision mirror of _shown_comparison_note
    above, same reasoning and same reused pattern."""
    lines = []
    for block in blocks or []:
        if block.get("type") != "decision":
            continue
        recommended_id = (block.get("recommended") or {}).get("project_id")
        for i, c in enumerate(block.get("candidates") or [], start=1):
            marker = " (recommended)" if c.get("project_id") == recommended_id else ""
            lines.append(
                f"{i}. {c.get('project_id', '')} \"{c.get('title', '')}\"{marker} — "
                f"overall_fit: {c.get('overall_fit')}%, skill_fit: {c.get('skill_fit')}, "
                f"timeline_fit: {c.get('timeline_fit')}%, difficulty_fit: {c.get('difficulty_fit')}, "
                f"uniqueness: {c.get('uniqueness_percent')}%, est: {c.get('estimated_weeks')}wk"
            )
    if not lines:
        return ""
    return "\n\n[Context — decision shown above, in order:\n" + "\n".join(lines) + "]"


def _project_detail_note(project_id: str, *, label: str, suffix: str = "") -> str:
    """Shared builder behind _active_project_note and _named_reference_note
    — the only thing that differs between "this is the student's active
    project" and "this is what the student's current message just named" is
    the label/suffix wording; the lookup and field formatting are identical.
    A plain get_project_details lookup — same tool the model itself has, not
    a second source of project data.

    Carries enough of the project's own fields (description, duration,
    skills — not just title/difficulty/domain/technologies) that grounded
    architecture/backend/technology answers don't need a second
    get_project_details round trip just to learn what the project actually
    requires — get_project_details already returns all of this, this just
    stops leaving most of it on the floor."""
    project, _block = chat_tools.call_tool("get_project_details", {"project_id": project_id})
    if project.get("error"):
        return ""
    tech = ", ".join((project.get("technologies") or [])[:6])
    skills = ", ".join((project.get("skills") or [])[:6])
    weeks = project.get("duration_weeks")
    description = (project.get("description") or "").strip()
    if len(description) > 240:
        description = description[:240].rsplit(" ", 1)[0].rstrip(",;: ") + "…"
    detail = ", ".join(
        part
        for part in [
            project.get("difficulty", ""),
            project.get("domain", ""),
            f"{weeks} weeks" if weeks else "",
            f"technologies: {tech}" if tech else "",
            f"skills: {skills}" if skills else "",
        ]
        if part
    )
    body = (
        f"{label}: {project['project_id']} \"{project.get('title', '')}\""
        f"{' — ' + description if description else ''}"
        f"{' (' + detail + ')' if detail else ''}"
    )
    return f"\n\n[Context — {body}{suffix}]"


def _active_project_note(selected_project_id: Optional[str]) -> str:
    """Tells the model which project is currently selected, if any, so a
    vague follow-up ('how should I build the backend?') doesn't need the
    student to re-name the project or the model to guess from search history."""
    if not selected_project_id:
        return ""
    return _project_detail_note(selected_project_id, label="active project")


def _idea_detail_note(idea: dict[str, Any], *, label: str, suffix: str = "") -> str:
    """Shared builder behind _active_idea_note and _named_reference_note —
    the idea-context mirror of _project_detail_note. No lookup needed:
    `idea` already carries its full fields (see chat_tools.select_idea, or a
    generated_project_ideas block), since a generated idea has no catalogue
    record to fetch it back from.

    Surfaces problem/solution too (select_idea already stores them, this just
    stops leaving them out of the note) — the same "what does this project
    actually require" grounding _project_detail_note carries via description,
    just from the idea's own fields instead of a Mongo lookup."""
    name = idea.get("name") if idea else None
    if not name:
        return ""
    tech = ", ".join((idea.get("technologies") or [])[:5])
    weeks = idea.get("duration_weeks")
    problem = (idea.get("problem") or "").strip()
    solution = (idea.get("solution") or "").strip()
    core = " — ".join(part for part in [f"problem: {problem}" if problem else "", f"solution: {solution}" if solution else ""] if part)
    detail = ", ".join(
        part
        for part in [
            idea.get("difficulty", ""),
            idea.get("domain", ""),
            f"{weeks}wk" if weeks else "",
            tech,
        ]
        if part
    )
    body = (
        f"{label}: \"{name}\""
        f"{' — ' + core if core else ''}"
        f"{' (' + detail + ')' if detail else ''}"
    )
    return f"\n\n[Context — {body}{suffix}]"


def _active_idea_note(selected_idea: Optional[dict[str, Any]]) -> str:
    """Tells the model which GENERATED idea is currently the student's active
    build target, if any — the idea-context mirror of _active_project_note.
    Mutually exclusive with an active project (see general_reply below), so
    at most one of these two notes is ever non-empty on a given turn."""
    if not selected_idea or not selected_idea.get("name"):
        return ""
    return _idea_detail_note(selected_idea, label="active idea (AI-generated, not a catalogue project)")


_QUOTED_NAME_RE = re.compile(r'"([^"]{1,200})"')

# Appended to every named-reference note so the model treats the fields as
# sufficient, rather than asking the student to restate what's already here
# — exactly the failure mode this function exists to close (see its own
# docstring below).
_NAMED_REFERENCE_SUFFIX = " — use these exact fields, never ask the student to redescribe it"


def _named_reference_note(
    message: str,
    history: Optional[list[dict[str, Any]]],
    *,
    selected_project_id: Optional[str] = None,
    selected_idea: Optional[dict[str, Any]] = None,
) -> str:
    """Grounds an exact quoted name in the CURRENT message directly against
    the idea/project it names, from the most recent matching block in
    `history` — every per-card action button in this app (Create Roadmap,
    Compare, Check Uniqueness, Improve Idea, ...) sends exactly this shape
    ('Create a roadmap for "QuizWhiz".', see frontend Dashboard.jsx's
    IDEA_ACTIONS/PROJECT_ACTIONS and Ideate.jsx) for a project/idea the
    student has NOT necessarily made their active build target — that's
    select_project/select_idea's job, triggered by 'Build This'/'select this
    one', not by asking about one shown idea among several.

    Exists because relying on the model to notice the same match against an
    older '[Context — generated ideas shown above]'/'[Context — projects
    shown above]' note (attached several turns back, on an *assistant*
    turn — see _shown_ideas_note/_shown_projects_note) proved unreliable in
    practice: live testing found the model asking the student to redescribe
    a project/idea whose exact fields (problem, solution, technologies,
    duration, ...) were already sitting in that note, unprompted by any real
    ambiguity — the note was present in the request the model received, so
    this is a parsing/attention gap in the model's behaviour, not a missing
    context bug. Handing the same fields back on THIS turn's own user
    message, addressed directly at the exact name just used, is far harder
    for the model to miss than a name match buried several turns back.

    Deliberately does not touch `selected_idea`/`selected_project_id` — this
    grounds one question about one named idea/project, not a change of the
    student's active build target, same as referring to 'the second one'
    doesn't select it either. Skips a name that's already the active
    project/idea (already covered by _active_project_note/_active_idea_note,
    see below) purely to avoid paying twice for the same tokens.
    """
    names = _QUOTED_NAME_RE.findall(message)
    if not names or not history:
        return ""

    remaining = set(names)
    found_ideas: dict[str, dict[str, Any]] = {}
    found_project_ids: dict[str, str] = {}
    for turn in reversed(history):
        if not remaining:
            break
        if turn.get("role") != "assistant":
            continue
        for block in turn.get("blocks") or []:
            if block.get("type") == "generated_project_ideas":
                for idea in block.get("ideas") or []:
                    if idea.get("name") in remaining:
                        found_ideas[idea["name"]] = idea
                        remaining.discard(idea["name"])
            elif block.get("type") == "project_recommendations":
                for project in block.get("projects") or []:
                    if project.get("title") in remaining:
                        found_project_ids[project["title"]] = project["project_id"]
                        remaining.discard(project["title"])

    notes = []
    for name in names:  # preserve the order the student's own message used
        if name in found_ideas:
            idea = found_ideas[name]
            if selected_idea and selected_idea.get("id") and selected_idea.get("id") == idea.get("id"):
                continue
            notes.append(
                _idea_detail_note(
                    idea,
                    label="idea the current message names, already shown in this conversation "
                    "(AI-generated, not a catalogue project)",
                    suffix=_NAMED_REFERENCE_SUFFIX,
                )
            )
        elif name in found_project_ids:
            project_id = found_project_ids[name]
            if selected_project_id and selected_project_id == project_id:
                continue
            notes.append(
                _project_detail_note(
                    project_id,
                    label="project the current message names, already shown in this conversation",
                    suffix=_NAMED_REFERENCE_SUFFIX,
                )
            )
    return "".join(notes)


def _resume_context_note(resume_skills: Optional[list[str]]) -> str:
    """Tells the model which skills were detected from the student's uploaded
    résumé, if any — the résumé-context mirror of _active_project_note. A
    plain list already computed by nlp/resume.py:detect_skills via
    /api/resume-suggest and attached to this conversation (see
    routes/assistant.py:attach_resume_skills), not something the model
    derives or invents itself. Independent of, and can coexist with, the
    active-project/active-idea notes above — a résumé's skills don't change
    just because a project gets selected."""
    if not resume_skills:
        return ""
    skills = ", ".join(resume_skills[:40])
    return f"\n\n[Context — résumé skills already on file for this conversation: {skills}]"


def _match_scores_from_history(history: Optional[list[dict[str, Any]]]) -> dict[str, float]:
    """project_id -> match_score, scanned from every project_recommendations
    block already in this conversation (most recent wins). Lets a comparison
    block carry a real score without re-ranking anything — see
    nlp/chat_tools.py:compare_projects, which has no query to score against."""
    scores: dict[str, float] = {}
    for turn in history or []:
        if turn.get("role") != "assistant":
            continue
        for block in turn.get("blocks") or []:
            if block.get("type") != "project_recommendations":
                continue
            for project in block.get("projects") or []:
                if project.get("match_score") is not None:
                    scores[project["project_id"]] = project["match_score"]
    return scores


class AssistantUnavailable(Exception):
    """Raised when GROQ_API_KEY isn't configured."""


@lru_cache(maxsize=1)
def _clients():
    """One Groq client per configured key (config.GROQ_API_KEYS) — usually
    just the one, but supports several so a rate-limited key doesn't stop
    the assistant. See _create_completion for how they're used.

    max_retries=0 disables the SDK's own built-in retry-with-backoff — left
    at its default, a single 429 makes the underlying client itself sleep
    out Groq's Retry-After (observed ~54s) *before* RateLimitError ever
    reaches _call_with_retry/_create_completion, silently defeating this
    module's own "don't wait, just rotate to the next key" strategy (see
    _call_with_retry's docstring) and stacking on top of the 413 shrink-and-
    retry ladder — together enough to blow past the frontend's request
    timeout even though the backend eventually succeeds. Retries here are
    already handled deliberately, one layer up, by key rotation and history
    shrinking, both of which react immediately instead of blocking a thread
    on a multi-second sleep.
    """
    if not config.AI_ASSISTANT_ENABLED:
        return []
    from groq import Groq

    return [Groq(api_key=key, max_retries=0) for key in config.GROQ_API_KEYS]


# Advances across calls (not per-retry) so successive turns start from a
# different key — spreads load proactively instead of only reacting once a
# key is already rate-limited.
_key_rotation = itertools.count()

# Bounded retry for TRANSIENT failures only (a network blip, a provider
# timeout, a momentary 5xx) — never for a permanent failure like a bad
# request or bad credentials, where retrying just wastes the same time to
# fail the same way again. 2 retries (3 attempts total) per key, doubling
# the delay each time, is enough to ride out a genuine blip without making a
# single turn hang: worst case here is ~1.5s of sleeping per key before
# moving on, not an unbounded wait.
MAX_LLM_RETRIES = 2
_LLM_RETRY_BASE_DELAY_SECONDS = 0.5


def _sleep(seconds: float) -> None:
    """A single indirection point so tests can assert on/skip the delay
    without monkeypatching the stdlib `time` module globally."""
    time.sleep(seconds)


def _call_with_retry(client: Any, kwargs: dict[str, Any]) -> Any:
    """One configured client, retrying a bounded number of times on a
    transient error before giving up on this client. A RateLimitError is
    deliberately NOT retried here — see _create_completion, which rotates to
    the next configured key instead of waiting out a 429 on this one."""
    from groq import APIConnectionError, InternalServerError

    transient = (APIConnectionError, InternalServerError)  # APITimeoutError subclasses APIConnectionError
    last_error: Optional[Exception] = None
    for attempt in range(MAX_LLM_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except transient as error:
            last_error = error
            if attempt < MAX_LLM_RETRIES:
                delay = _LLM_RETRY_BASE_DELAY_SECONDS * (2**attempt)
                log.warning(
                    "Groq call failed (%s), retrying in %.1fs (attempt %d/%d)",
                    type(error).__name__,
                    delay,
                    attempt + 1,
                    MAX_LLM_RETRIES,
                )
                _sleep(delay)
                continue
    raise last_error  # every retry on this client was exhausted


# A live 502 on POST /api/conversations/<id>/messages was traced to every
# configured key returning a genuine Groq 429 within the same second — all
# GROQ_API_KEYS share one Groq organization's tokens-per-minute pool (see
# _clients' docstring), so rotating keys does nothing for this specific
# failure; only waiting out the shared window does. Reproduced live: Groq's
# own `retry-after` header read 3 (body: "Please try again in 2.66s") the
# moment a tools-heavy turn (TOOL_SCHEMAS sent every round, plus a nested
# ideation call) tipped the account's 8,000 TPM budget — precisely the
# "click Retry and it works" symptom, since a few seconds later the same
# request succeeds unchanged. Honoring a short provider-reported wait once
# turns that into the turn just succeeding, slower, instead of failing and
# waiting on the student to notice and retry by hand. Capped so this can
# never turn into the multi-second-to-a-minute stall a large deficit's
# retry-after would cause (that case is left exactly as before: an
# immediate, retryable 502) — a bounded, provider-signalled single retry,
# not a blind backoff loop.
_RATE_LIMIT_RETRY_AFTER_CEILING_SECONDS = 5.0


def _rate_limit_retry_after(error: Exception) -> Optional[float]:
    """Groq's own `retry-after` (seconds) off a RateLimitError's response, if
    present and parseable — None otherwise (missing header, or a fake/test
    error with no response at all), which callers treat as "don't wait"."""
    response = getattr(error, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header is None:
        return None
    try:
        return float(header)
    except (TypeError, ValueError):
        return None


def _create_completion(*, _rate_limit_retry: bool = True, **kwargs: Any):
    """client.chat.completions.create(**kwargs), retrying transient failures
    on the current key (_call_with_retry) and rotating across every
    configured Groq key on a 429, a 413 (see below), or once retries are
    exhausted on a transient error — before giving up.

    Most permanent failures (bad request, bad credentials, ...) are never
    retried or rotated past: they would fail identically on every key, so
    they propagate on the first attempt. A 413 is the one deliberate
    exception — it means THIS key's account tokens-per-minute budget can't
    fit the request, which is a property of the account behind the key, not
    of the request itself, so a different key (especially one on a
    different Groq account, with its own independent budget) genuinely can
    succeed where this one failed.

    If every configured key comes back rate-limited, and Groq's own
    retry-after on that last 429 is short (see
    _RATE_LIMIT_RETRY_AFTER_CEILING_SECONDS), waits that long once and
    retries the whole key rotation exactly once more (`_rate_limit_retry`
    guards against a second such wait, so this can add at most one bounded
    delay, never a loop) — see the constant's docstring above for why. Any
    other outcome (a longer/absent retry-after, or still rate-limited after
    the one retry) raises exactly as before this existed.

    With one key configured and no failures (the common case) this is
    exactly the single request it always was.
    """
    from groq import APIConnectionError, APIStatusError, InternalServerError, RateLimitError

    clients = _clients()
    if not clients:
        raise AssistantUnavailable("GROQ_API_KEY is not configured.")

    start = next(_key_rotation) % len(clients)
    ordered = clients[start:] + clients[:start]

    last_error: Optional[Exception] = None
    for index, client in enumerate(ordered):
        has_next_key = index < len(ordered) - 1
        try:
            return _call_with_retry(client, kwargs)
        except (RateLimitError, APIConnectionError, InternalServerError) as error:
            last_error = error
            if has_next_key:
                if isinstance(error, RateLimitError):
                    log.warning("Groq key %d/%d rate-limited, trying next key", index + 1, len(ordered))
                else:
                    log.warning(
                        "Groq key %d/%d failed after retries (%s), trying next key",
                        index + 1,
                        len(ordered),
                        type(error).__name__,
                    )
            continue
        except APIStatusError as error:
            # A 413 ("request too large for this key's tokens-per-minute
            # budget") is a property of the ACCOUNT behind this key, not of
            # the request itself — a different key, especially one on a
            # different Groq account (its own independent TPM budget), can
            # genuinely succeed where this one just failed. Worth trying the
            # next key; not worth a same-key backoff retry first (see
            # _call_with_retry) since this account's ceiling won't have
            # moved a few hundred milliseconds later. Any other APIStatusError
            # (bad request, bad credentials, ...) is a permanent failure that
            # would fail identically on every key, so it still propagates
            # immediately, exactly as before this branch existed.
            last_error = error
            if getattr(error, "status_code", None) == 413 and has_next_key:
                log.warning("Groq key %d/%d rejected the request as too large (413), trying next key", index + 1, len(ordered))
                continue
            raise

    if _rate_limit_retry and isinstance(last_error, RateLimitError):
        wait = _rate_limit_retry_after(last_error)
        if wait is not None and wait <= _RATE_LIMIT_RETRY_AFTER_CEILING_SECONDS:
            log.warning(
                "Every Groq key rate-limited; provider reports the shared window resets in "
                "%.1fs — waiting once and retrying",
                wait,
            )
            _sleep(wait)
            return _create_completion(_rate_limit_retry=False, **kwargs)

    raise last_error  # every configured key is rate-limited, too-large, or failing


# How long a model-reachability result is trusted before re-checking — long
# enough that a health-check poller (uptime monitors commonly hit /api/health
# every 10-60s) can't turn into a steady stream of Groq calls, short enough
# that a real outage or a deprecated model (see below) is caught within one
# operator's coffee break, not silently for hours.
_MODEL_STATUS_CACHE_SECONDS = 300
_model_status_cache: dict[str, Any] = {"checked_at": 0.0, "result": None}


def model_status() -> Optional[dict[str, Any]]:
    """Whether the configured Groq model(s) are actually reachable right now.

    Exists because neither chat()/general_reply() nor /api/health's other
    checks (Mongo, the search index) ever notice a dead/renamed model on
    their own — that failure is only discovered by whichever real user
    happens to send the next chat message, exactly what let GROQ_MODEL sit
    pointed at a model Groq had already removed from its catalogue until a
    live request surfaced it (see config.py's own comment on that incident).

    Uses `client.models.list()` — a metadata call, never a chat completion —
    so this costs no completion tokens and never touches the tokens-per-
    minute budget the rest of this module's reliability logic (key rotation,
    history shrinking) exists to protect. Result is cached for
    `_MODEL_STATUS_CACHE_SECONDS`; within that window this is a dict lookup,
    not a network call.

    Returns None if the assistant isn't configured at all (no key, nothing to
    check) — distinct from an empty/failed result, which means it IS
    configured but currently unreachable.
    """
    if not config.AI_ASSISTANT_ENABLED:
        return None

    now = time.monotonic()
    cached = _model_status_cache["result"]
    if cached is not None and now - _model_status_cache["checked_at"] < _MODEL_STATUS_CACHE_SECONDS:
        return cached

    result = _check_model_status()
    _model_status_cache["result"] = result
    _model_status_cache["checked_at"] = now
    return result


def _check_model_status() -> dict[str, Any]:
    """One real (uncached) reachability check — always returns a result dict,
    never raises, so a Groq-side outage degrades /api/health's AI section
    gracefully instead of breaking the whole health endpoint."""
    clients = _clients()
    if not clients:
        return {"reachable": False, "error": "No Groq client configured."}

    try:
        available_ids = {model.id for model in clients[0].models.list().data}
    except Exception as error:  # noqa: BLE001
        return {"reachable": False, "error": str(error)}

    missing = [model_id for model_id in (config.GROQ_MODEL, config.GROQ_TOOL_MODEL) if model_id not in available_ids]
    return {
        "reachable": not missing,
        "checked_model": config.GROQ_MODEL,
        "checked_tool_model": config.GROQ_TOOL_MODEL,
        "missing_models": missing,
    }


def _system_message(doc: dict[str, Any]) -> dict[str, str]:
    content = _SYSTEM_TEMPLATE.format(
        title=doc.get("title", ""),
        domain=doc.get("domain", ""),
        difficulty=doc.get("difficulty", ""),
        description=doc.get("description", ""),
        technologies=", ".join(doc.get("technologies", [])),
        skills=", ".join(doc.get("skills", [])),
    )
    return {"role": "system", "content": content}


def _history_messages(
    history: Optional[list[dict[str, Any]]],
    *,
    with_shown_projects: bool = False,
    max_messages: int = MAX_HISTORY_MESSAGES,
) -> list[dict[str, str]]:
    """Caller-supplied turns, trimmed and validated to role/content shape.

    Shared by `reply()` and `general_reply()` — neither endpoint keeps a
    server-side session for the *model call itself*; both are handed the
    running conversation and just replay it, capped so a long chat can't
    grow the request without bound.

    `max_messages` overrides the default trim window — see
    `_HISTORY_SHRINK_STEPS` below, which retries a turn with a smaller window
    when even the default-sized request is rejected as too large for the
    account's tokens-per-minute budget.

    `with_shown_projects` appends a shown-projects/shown-ideas/comparison/
    decision note (see `_shown_projects_note`/`_shown_ideas_note`/
    `_shown_comparison_note`/`_shown_decision_note`) — used only by
    `general_reply()`, which is the one entry point where a stored turn can
    carry `blocks`. Only the MOST RECENT turn of each kind gets its note
    replayed, not every one in the trimmed window: once a fresh batch of
    projects or ideas is shown (or a fresh comparison/decision is made),
    that's the current set the student is looking at (Ideate.jsx's own
    mergeIdea replaces the grid the same way on a new batch) — older ones
    are superseded, not additive context. Without this cap, a conversation
    that searches or generates ideas more than once keeps replaying every
    earlier turn's full note (per-idea problem/solution/unique_point text,
    for every idea, every time) on every later turn — unbounded growth that
    has driven a real request over a model's tokens-per-minute budget (a 413
    from Groq, not a flaky rate limit — retrying an identical oversized
    request fails identically).
    """
    # `[-0:]` is a classic Python trap — it slices the WHOLE list, not none of
    # it, since -0 == 0 — so the max_messages == 0 shrink step (see
    # _HISTORY_SHRINK_STEPS) needs its own branch rather than falling through
    # to the general slice.
    trimmed = (history or [])[-max_messages:] if max_messages > 0 else []

    last_projects_index: Optional[int] = None
    last_ideas_index: Optional[int] = None
    last_comparison_index: Optional[int] = None
    last_decision_index: Optional[int] = None
    if with_shown_projects:
        for i, turn in enumerate(trimmed):
            if turn.get("role") != "assistant":
                continue
            blocks = turn.get("blocks") or []
            if any(b.get("type") == "project_recommendations" for b in blocks):
                last_projects_index = i
            if any(b.get("type") == "generated_project_ideas" for b in blocks):
                last_ideas_index = i
            if any(b.get("type") == "comparison" for b in blocks):
                last_comparison_index = i
            if any(b.get("type") == "decision" for b in blocks):
                last_decision_index = i

    messages = []
    for i, turn in enumerate(trimmed):
        role = turn.get("role")
        content = (turn.get("content") or "")[:MAX_MESSAGE_CHARS]
        if role not in ("user", "assistant") or not content:
            continue
        if with_shown_projects and role == "assistant":
            if i == last_projects_index:
                content += _shown_projects_note(turn.get("blocks"))
            if i == last_ideas_index:
                content += _shown_ideas_note(turn.get("blocks"))
            if i == last_comparison_index:
                content += _shown_comparison_note(turn.get("blocks"))
            if i == last_decision_index:
                content += _shown_decision_note(turn.get("blocks"))
        messages.append({"role": role, "content": content})
    return messages


def _complete(messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> str:
    completion = _create_completion(
        model=config.GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        # GROQ_MODEL is a reasoning model — without this, its hidden
        # "thinking" tokens can consume the whole max_tokens budget before
        # any visible answer is written, returning "" with no error (see
        # config.py's GROQ_MODEL comment).
        reasoning_effort="low",
    )
    if not completion.choices:
        # Malformed/empty provider response — rare, but returning "" here
        # (instead of an IndexError) lets the caller's own "nothing useful
        # came back" handling take over rather than crashing the request.
        log.warning("Groq completion returned no choices")
        return ""
    # content can legitimately be None (e.g. a response shaped for tool use
    # rather than prose) even though reply()/_complete() never send `tools` —
    # a provider quirk is still possible, and `.strip()` on None would crash.
    return (completion.choices[0].message.content or "").strip()


# A turn's fixed overhead (the system prompt, and for general_reply() also
# every tool schema) can't be shrunk without changing what the assistant can
# do — but the history replayed alongside it can. Shrinking that window is
# the one lever left once _create_completion's own 413 rotation has already
# tried every configured key and every one of them rejected the request as
# too large: that means the request is oversized for every account behind
# them, not just rate-limited on one, so a different key won't help either
# (see _create_completion's docstring). Retrying the identical request would
# fail identically forever (this is exactly the "grown too large" case
# routes/assistant.py used to send straight to the student as "start a new
# chat") — a smaller request is the only real fix, so these steps retry the
# whole turn with progressively less history before giving up. 0 is the last
# resort: no prior turns replayed at all, just the system/tool overhead plus
# this one message — still grounded via the active-project/active-idea/
# résumé notes, which are attached to the current message regardless of
# history, not to the trimmed window.
_HISTORY_SHRINK_STEPS = (MAX_HISTORY_MESSAGES, 6, 3, 0)


def _is_context_too_large(error: Exception) -> bool:
    """True for the specific Groq 413 that _create_completion propagates once
    every configured key has rejected a request as too large — see its own
    docstring. Distinguishes that one shrink-and-retry case from every other
    exception (rate-limit exhaustion, a malformed request, ...), which a
    smaller history window cannot fix and so must propagate unchanged."""
    from groq import APIStatusError

    return isinstance(error, APIStatusError) and getattr(error, "status_code", None) == 413


def _effective_shrink_steps(history_length: int) -> tuple[int, ...]:
    """_HISTORY_SHRINK_STEPS, deduplicated against how much history there
    actually is to trim.

    A short conversation can already be too large purely on the fixed
    system-prompt/tool-schema overhead plus one note-bearing turn (e.g. a
    turn that just generated several project ideas) — trying caps of 12,
    then 6, then 3 against a 2-message history sends the exact same
    oversized request three times before ever reaching the one cap (0) that
    actually changes anything. Each of those wasted attempts still pays for
    a full key-rotation pass (and for general_reply's tool-calling turn, a
    full LLM round trip), which is real, user-visible latency for a turn
    that could not have succeeded any of those times — worth skipping
    outright rather than paying for on the way to the cap that might.
    """
    steps: list[int] = []
    for cap in _HISTORY_SHRINK_STEPS:
        effective = min(cap, max(history_length, 0))
        if not steps or steps[-1] != effective:
            steps.append(effective)
    return tuple(steps)


def reply(doc: dict[str, Any], message: str, history: Optional[list[dict[str, str]]] = None) -> str:
    """One assistant reply, grounded in `doc`, given the running `history`.

    Retries with a smaller history window (`_HISTORY_SHRINK_STEPS`, deduped
    against the actual history length by `_effective_shrink_steps`) on a 413
    that survived key rotation in `_create_completion` — see that function's
    docstring and `_HISTORY_SHRINK_STEPS` above for why a smaller request,
    not a different key, is the fix for that specific failure. Any other
    exception propagates from the first attempt, unchanged.
    """
    steps = _effective_shrink_steps(len(history or []))
    for step, cap in enumerate(steps):
        messages = [
            _system_message(doc),
            *_history_messages(history, max_messages=cap),
            {"role": "user", "content": message[:MAX_MESSAGE_CHARS]},
        ]
        try:
            return _complete(messages, temperature=0.4, max_tokens=600)
        except Exception as error:  # noqa: BLE001
            if step == len(steps) - 1 or not _is_context_too_large(error):
                raise
            log.warning(
                "Request too large for every configured key with %d history messages; "
                "retrying with a smaller history window",
                cap,
            )


def general_reply(
    message: str,
    history: Optional[list[dict[str, Any]]] = None,
    selected_project_id: Optional[str] = None,
    selected_idea: Optional[dict[str, Any]] = None,
    resume_skills: Optional[list[str]] = None,
) -> tuple[str, list[dict[str, Any]], Optional[str], Optional[dict[str, Any]]]:
    """One assistant turn with no single project fixed in scope — the
    Dashboard chat.

    Returns (content, blocks, selected_project_id, selected_idea). This can
    call tools (nlp/chat_tools.py) before answering, so it can recommend real
    projects, compare them, check skill gaps, predict timelines, or generate
    a roadmap/synopsis rather than inventing any of that. `blocks` is built
    from this turn's own tool results — never parsed out of the model's text
    — so rendering never depends on the model emitting exact JSON.

    `selected_project_id`/`selected_idea` in and out are the same values
    unless the model calls select_project/select_idea this turn, in which
    case the new selection is returned so the caller (routes/assistant.py)
    can persist it on the conversation. The two are mutually exclusive —
    selecting one clears the other, see the loop below.

    `resume_skills` is read-only context here (see routes/assistant.py:
    attach_resume_skills) — nothing in this turn's tool loop mutates it, so
    unlike the two selections above it is not part of the return value; the
    caller already has whatever it passed in.

    Retries the whole turn with a smaller history window
    (`_HISTORY_SHRINK_STEPS`, deduped against the actual history length by
    `_effective_shrink_steps`) on a 413 that survived key rotation in
    `_create_completion` — the tool-calling system prompt plus every tool
    schema (GROQ_TOOL_MODEL) is already substantial fixed cost per request,
    so a conversation that has shown several batches of projects/ideas can
    still outgrow the account's tokens-per-minute budget even after that
    per-key rotation. Safe to re-run from scratch: every chat_tools.py tool
    is a read (or a same-turn-only selection returned to, not persisted by,
    this function — see routes/assistant.py, which only writes after
    general_reply returns), so repeating the tool loop on retry has no
    side effect to duplicate. See reply()'s docstring for the same trade-off
    on the simpler project-grounded chat.

    Note the unavoidable trade-off at the last-resort (0-history) step: a
    GENERATED idea/project the student hasn't explicitly selected is only
    nameable via the shown-ideas/shown-projects note threaded through
    history (see _shown_ideas_note/_shown_projects_note) — dropping all
    history to fit the budget drops that note too, so the model may
    correctly (per its own system-prompt instructions) ask which idea/
    project is meant rather than guess. An explicitly selected project/idea
    is unaffected: its own note is attached to the current message
    regardless of history (see _active_project_note/_active_idea_note).
    """
    if not config.AI_ASSISTANT_ENABLED:
        raise AssistantUnavailable("GROQ_API_KEY is not configured.")

    steps = _effective_shrink_steps(len(history or []))
    for step, cap in enumerate(steps):
        try:
            return _general_reply_once(message, history, cap, selected_project_id, selected_idea, resume_skills)
        except Exception as error:  # noqa: BLE001
            if step == len(steps) - 1 or not _is_context_too_large(error):
                raise
            log.warning(
                "Request too large for every configured key with %d history messages; "
                "retrying the turn with a smaller history window",
                cap,
            )


def _general_reply_once(
    message: str,
    history: Optional[list[dict[str, Any]]],
    history_cap: int,
    selected_project_id: Optional[str],
    selected_idea: Optional[dict[str, Any]],
    resume_skills: Optional[list[str]],
) -> tuple[str, list[dict[str, Any]], Optional[str], Optional[dict[str, Any]]]:
    """One attempt at general_reply()'s full tool-calling turn, at a given
    history window size — factored out purely so general_reply() can retry
    the entire turn with a smaller `history_cap` on a 413 (see
    _HISTORY_SHRINK_STEPS) without duplicating the tool loop below."""
    messages: list[dict[str, Any]] = [
        _GENERAL_SYSTEM_MESSAGE,
        *_history_messages(history, with_shown_projects=True, max_messages=history_cap),
        {
            "role": "user",
            "content": (
                message[:MAX_MESSAGE_CHARS]
                + _active_project_note(selected_project_id)
                + _active_idea_note(selected_idea)
                + _resume_context_note(resume_skills)
                + _named_reference_note(
                    message[:MAX_MESSAGE_CHARS],
                    history,
                    selected_project_id=selected_project_id,
                    selected_idea=selected_idea,
                )
            ),
        },
    ]

    blocks_by_type: dict[str, dict[str, Any]] = {}

    for round_index in range(MAX_TOOL_ROUNDS):
        final_round = round_index == MAX_TOOL_ROUNDS - 1
        # Deliberately no fallback here on a request error (e.g. Groq
        # rejecting a malformed tool call): retrying the same turn without
        # `tools` was tried and rejected — a model primed by the system
        # prompt to call a tool, suddenly told it has none, doesn't answer
        # honestly, it free-texts a fake "search result" instead. That is
        # exactly the hallucination this whole RAG design exists to prevent,
        # so a genuine failure here should surface as a failure (caught by
        # routes/assistant.py, 502, retryable) rather than a fabricated answer.
        completion = _create_completion(
            model=config.GROQ_TOOL_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=700,
            tools=chat_tools.TOOL_SCHEMAS,
            tool_choice="auto",
        )
        if not completion.choices:
            # Malformed/empty provider response — same "return what we have,
            # never crash" contract as the final-round branch just below.
            log.warning("Groq completion returned no choices")
            return "", list(blocks_by_type.values()), selected_project_id, selected_idea
        msg = completion.choices[0].message

        if not msg.tool_calls or final_round:
            # On the round cap, stop regardless of what the model wants next.
            # tool_choice="none" was tried here first — force a tool-free
            # completion once the budget is spent — and it was worse: Groq
            # 400s with "Tool choice is none, but model called a tool" when a
            # model this deep into a tool-calling turn tries to call one
            # anyway (reproduced directly, not hypothetical), which would
            # throw on exactly the turn this branch exists to always answer.
            # Just taking whatever text is already present is the one option
            # that cannot itself fail.
            content = (msg.content or "").strip()
            if "comparison" in blocks_by_type:
                scores = _match_scores_from_history(history)
                for project in blocks_by_type["comparison"]["projects"]:
                    if project["project_id"] in scores:
                        project["match_score"] = scores[project["project_id"]]
            return content, list(blocks_by_type.values()), selected_project_id, selected_idea

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments},
                    }
                    for call in msg.tool_calls
                ],
            }
        )

        for call in msg.tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}

            try:
                result, block = chat_tools.call_tool(call.function.name, arguments)
            except Exception:  # noqa: BLE001
                log.exception("Tool call failed: %s(%r)", call.function.name, arguments)
                result, block = {"error": "Tool call failed."}, None

            if block:
                # Overwrites any earlier block of the same type this turn —
                # e.g. a second search_projects call replaces the first
                # search's cards rather than stacking stale ones next to
                # fresh ones, same as the single-slot behaviour this
                # generalises. Different-typed blocks (a comparison *and* a
                # skill-gap result) both survive since they key separately.
                blocks_by_type[block["type"]] = block
                if block["type"] == "project_selected":
                    selected_project_id = block["project"]["project_id"]
                    selected_idea = None
                elif block["type"] == "idea_selected":
                    selected_idea = block["idea"]
                    selected_project_id = None

            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)}
            )

    # Unreachable: `final_round` is True on the loop's last iteration, and the
    # branch above always returns on that iteration regardless of tool_calls.
    return "", [], selected_project_id, selected_idea
