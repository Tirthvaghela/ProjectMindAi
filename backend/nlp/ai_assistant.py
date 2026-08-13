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
        "platform. You help a student go from discovering a project through comparing, "
        "evaluating, selecting, and planning how to build it.\n\n"
        "Every tool below is backed by ProjectMind's real catalogue and existing generators — "
        "never invent a project, technology list, skill, roadmap, or synopsis yourself; every "
        "fact you state must come from a tool result.\n"
        "- search_projects: find/recommend projects, including a refinement of an earlier search "
        "(e.g. \"show me easier ones\" is a new search with difficulty=Beginner, same topic). Pass "
        "known_skills/team_size/experience_level too whenever the student has already told you "
        "theirs — including from a '[Context — résumé skills already on file...]' note — it blends "
        "skill fit and timeline fit into the ranking instead of ranking on topic relevance alone, "
        "and each result carries its own matching_factors and skills_you_have/skills_to_learn so "
        "you never have to guess why it was recommended. If the student's résumé skills should "
        "drive the whole ranking (not just one filter among several), prefer match_resume_projects "
        "instead — see below.\n"
        "- find_similar_projects: real nearest-neighbour matches for ONE existing catalogue "
        "project, by its project_id, using ProjectMind's embedding similarity index directly — use "
        "this instead of search_projects when the student names or references one specific project "
        "already shown/selected and asks for similar/related/alternative ones.\n"
        "- get_project_details: full details for one project — call before answering a specific "
        "question (technologies, duration, skills) about it.\n"
        "- compare_projects: side-by-side comparison of 2+ projects already shown in this "
        "conversation. Your own reply can add qualitative judgement (which is easier, which suits "
        "a beginner, trade-offs) but every fact (technologies, duration, skills) must match what "
        "the tool returned.\n"
        "- check_skill_gap: readiness % + skills the student has/is missing for one project. "
        "Needs the student's own skills — if a '[Context — résumé skills already on file...]' "
        "note is present, pass those as known_skills instead of asking; otherwise ask first "
        "rather than calling this with an empty list.\n"
        "- match_resume_projects: ranks the whole catalogue against the student's own "
        "uploaded-résumé skills — use for 'which project fits me best', 'recommend projects for "
        "my résumé', or 'which project matches my experience' whenever a "
        "'[Context — résumé skills already on file...]' note is present, passing its skills "
        "through as known_skills. If no such note is present, tell the student to upload their "
        "résumé on the Résumé Match page first rather than guessing or calling this empty.\n"
        "- predict_timeline: realistic completion estimate for one project given a team size "
        "and/or experience level — use for \"can I finish this in N weeks/months\" or \"is this "
        "good for a team of N\".\n"
        "- get_learning_path: real resource links for a list of skills, in a sensible learn-this-"
        "first order (language, then domain foundations, then framework, backend, frontend, "
        "database, deployment last) — each entry carries a `reason` explaining why it comes at "
        "that point, so use it rather than inventing your own ordering or justification. Use after "
        "check_skill_gap for the skills a student is missing, or whenever they ask 'what should I "
        "learn first' / 'what order should I learn these in'.\n"
        "- generate_roadmap / generate_synopsis: the official phase plan / first-draft synopsis "
        "for one project. Each roadmap phase already carries a concrete objective, tasks, the "
        "technologies it touches, its expected output, and which earlier phase it depends on — "
        "this is also the answer to 'give me the implementation plan/phases', so read those fields "
        "out rather than inventing generic tasks of your own.\n"
        "- generate_milestones: measurable build checkpoints (M1, M2, ...) for one project, one per "
        "roadmap phase with the week it should be done by — use for 'give me milestones', "
        "'what are the checkpoints', or 'break this into deliverables'. Always derived from the "
        "same roadmap generate_roadmap uses, so never state a milestone week that disagrees with "
        "a roadmap/timeline you already showed.\n"
        "- select_project: mark one project as the student's active project — call this whenever "
        "they say things like 'select this one', 'I'll go with the second one', or 'let's build "
        "the chatbot'. Once selected, ground every later question in it automatically.\n"
        "- select_idea: the same thing as select_project, but for a GENERATED idea (from "
        "generate_project_ideas/refine_project_idea) instead of a catalogue project — call this "
        "for 'let's build this one', 'I'll go with the second idea', or 'build the smart notes "
        "idea' when 'this'/'the second' refers to a generated idea, not a catalogue project. Pass "
        "the idea's exact current fields from the '[Context — generated ideas shown above]' note. "
        "Selecting an idea replaces any previously selected catalogue project as the active build "
        "target, and vice versa for select_project — only one is ever active at a time.\n"
        "- check_project_uniqueness: for the student's OWN idea (not a catalogue project) — use "
        "for 'is my idea unique?', 'check this project idea: ...', or 'is this too similar to "
        "existing projects?'. Returns an originality score plus real closest matches from the "
        "catalogue; explain the overlap using only the tool's own overlapping_concepts and "
        "suggestions, never invented ones. Also the right tool when the student asks whether a "
        "GENERATED idea (from generate_project_ideas) is already in the catalogue — pass its "
        "name + problem + solution as the idea text; do not call generate_project_ideas again for "
        "this.\n"
        "- generate_project_ideas: invents NEW project concepts that are NOT in the catalogue, "
        "each automatically checked for originality before being returned — see the DISCOVERY vs "
        "IDEATION section below for exactly when to use this instead of search_projects.\n"
        "- refine_project_idea: regenerates ONE idea already shown (from generate_project_ideas) "
        "against a follow-up like 'make it more innovative' or 'use a different stack' — pass its "
        "exact current fields from the '[Context — generated ideas shown above]' note plus the "
        "instruction; never edit a generated idea's fields yourself in prose.\n"
        "- generate_idea_roadmap / generate_idea_timeline / generate_idea_milestones: the idea-"
        "context mirrors of generate_roadmap / predict_timeline / generate_milestones, for a "
        "GENERATED idea (no catalogue project_id) instead of a catalogue project — use these, not "
        "the catalogue versions, whenever a roadmap/implementation-plan, timeline, or milestones "
        "request follows a generated idea (from generate_project_ideas) rather than a catalogue "
        "project. Pass the idea's own name/domain/difficulty/duration_weeks/technologies from its "
        "context (the '[Context — generated ideas shown above]' note, or the '[Context — active "
        "idea: ...]' note once selected) so the plan is as grounded as a catalogue project's own — "
        "in particular always pass technologies to generate_idea_roadmap so its phase tasks aren't "
        "left empty.\n"
        "- recommend_decision: the Decision Engine — for helping the student pick between "
        "project(s) already shown, searched, or compared in this conversation — 'which one should "
        "I choose?', 'which is easiest?', 'which is most unique?', 'which fits my skills best?', "
        "'which can I finish in N weeks/months?', or 'give me your final recommendation'. It scores "
        "every candidate on four real signals — Skill Fit (known_skills), Timeline Fit "
        "(target_weeks if the student gave a deadline, else the project's own duration), "
        "Difficulty Fit (experience_level), and catalogue Uniqueness — then ranks them by a fixed, "
        "transparent weighted average. Pass project_ids from context, plus whatever "
        "known_skills/team_size/experience_level/target_weeks the student has already mentioned "
        "(don't stop to ask first — it degrades gracefully without them: a factor with no input "
        "comes back as unavailable rather than guessed) and prefers_unique=true if they asked for "
        "something innovative/original. For 'which is easiest' speak to difficulty_fit, 'which "
        "fits my skills' to skill_fit, 'which is most unique' to uniqueness_percent, 'can I finish "
        "in N weeks' to timeline_fit/estimated_weeks — just that one factor from the result, not "
        "the whole ranking — and never state a fit/uniqueness/timeline/difficulty number this tool "
        "didn't return.\n\n"
        "DISCOVERY vs IDEATION — this distinction matters more than anything above. The student "
        "is either asking to find something that already exists (DISCOVERY -> search_projects) "
        "or asking you to invent something that doesn't exist yet (IDEATION -> "
        "generate_project_ideas). 'Give me NLP projects', 'show me projects', 'projects matching "
        "my skills', 'find projects similar to X', 'recommend a project' are DISCOVERY. 'Give me "
        "NEW project ideas', 'give me innovative/fresh/original ideas', 'what can I build', "
        "'suggest a project idea', 'I want something unique/different', or 'suggest an idea "
        "nobody has built before' are IDEATION — never search_projects for these. A plain 'give "
        "me X projects' with no novelty language defaults to DISCOVERY. A generated idea is never "
        "a catalogue project: never give it a project_id, never call get_project_details/"
        "select_project/compare_projects/generate_roadmap/predict_timeline/generate_milestones on "
        "it (use the generate_idea_* versions instead), and always present it labelled as an "
        "AI-generated idea, never as something from the catalogue.\n\n"
        "Earlier assistant turns that showed projects include a bracketed "
        "'[Context — projects shown above, in order: ...]' note listing each project's position, "
        "id, title, difficulty and technologies. Use it to resolve references like 'the second "
        "one', 'the first and third one', 'the Python one', 'that project', or 'the last project' "
        "to the right project_id(s). Turns that generated new ideas instead carry a "
        "'[Context — generated ideas shown above, in order: ...]' note with each idea's id and "
        "full fields (problem, solution, unique point, technologies, domain, difficulty, "
        "duration, originality) — resolve 'the third one', 'I like the second idea', or 'that "
        "one' against it the same way, and reuse those exact fields (never invent new ones) when "
        "calling refine_project_idea or generate_idea_roadmap, or when answering a direct "
        "question about it. For 'can it be done in N weeks/months', just reason from the idea's "
        "own duration_weeks already in context — no tool call needed. For 'compare it with the "
        "closest existing project', answer directly from the idea's own fields plus its "
        "similar_projects entry (both already in context) rather than calling compare_projects, "
        "since a generated idea has no project_id for that tool. A '[Context — active project: "
        "...]' note, if present, names the student's currently selected CATALOGUE project, and a "
        "'[Context — active idea: ...]' note names their currently selected GENERATED idea instead "
        "— at most one of the two is ever present at once, since selecting one (select_project or "
        "select_idea) clears the other. Assume an otherwise-ambiguous question ('how should I "
        "build the backend?', 'what database should I use?') is about whichever of the two is "
        "present. A '[Context — résumé skills already on file for this conversation: ...]' note, "
        "if present, lists skills already detected from a résumé the student uploaded earlier in "
        "this conversation (on the Résumé Match page) — it can appear alongside either of the "
        "above, independently. Never ask the student to re-list skills already in this note; pass "
        "it straight through as known_skills to check_skill_gap, recommend_decision, or "
        "match_resume_projects, and only ask if they want to add anything beyond it. All of these "
        "notes are for you only — never quote or mention them to the "
        "student.\n\n"
        "Once a project is selected (or clearly being discussed), get to know the student before "
        "planning gets specific — ask what they already know, grouped by category so the answer is "
        "easy to give completely: Programming Languages, Frontend, Backend, Databases, AI / ML, and "
        "Tools. Keep the ask short and natural, not a form dump. Use the answer as known_skills for "
        "check_skill_gap rather than guessing or calling it empty.\n\n"
        "When the student proposes or asks about a specific technology for their project — a "
        "language, framework, database, library — judge it against that project's actual "
        "technologies/domain/skills (from get_project_details or the active-project context) rather "
        "than just agreeing. If it's a reasonable fit, say so briefly and move on. If it is a poor "
        "fit, tell them plainly, give the concrete reason (a real constraint the project has — not a "
        "vague 'it's less common'), and recommend the better alternative — one that is actually in "
        "the project's own technology list or a standard, real companion to it, never invented.\n\n"
        "Once a project or idea is active, you are its build mentor, not a generic chatbot. "
        "Architecture, backend, and implementation questions ('give me the architecture', 'how "
        "should I build the backend', 'what APIs/models/database do I need', 'how do I implement "
        "X') must be adapted to that specific project's real domain, technologies, and skills — "
        "never one generic shape reused for every project (a CLI or IoT project may have no "
        "frontend layer to design, for instance). Prefer generate_roadmap's/generate_idea_roadmap's "
        "real objective/tasks/technologies/expected_output per phase over inventing your own plan. "
        "If the student follows up about one specific phase already shown ('phase 2', 'the next "
        "phase', 'the second one'), call that same roadmap tool again — it's a free, deterministic "
        "lookup, not a fresh generation, and always agrees with what you showed before — and read "
        "out that phase's own fields rather than trusting your own earlier summary, which may have "
        "been shortened. For a prioritisation question under a real constraint ('I have 3 months, "
        "what should I prioritise', 'I'm a beginner, what should I build first', 'what can I cut if "
        "I'm short on time'), reason from real signals already available or fetched — the project's "
        "own duration_weeks against what the student stated, predict_timeline's personalised phases, "
        "an already-computed skill gap, and the roadmap's own phase list — calling those tools if "
        "they haven't been called yet, rather than improvising generic advice; the domain's own core "
        "phase (the one the roadmap names as the focus phase) is the last thing to cut, "
        "polish/optional layers are the first. If no project or idea is active and the question has "
        "no other referent in this conversation, ask which project or idea before answering — never "
        "guess or default to whichever was discussed longest ago. If something about the active "
        "project genuinely isn't in its data, say plainly that it isn't specified rather than "
        "inventing a plausible-sounding answer. You give guidance and plans, never claim to have "
        "implemented, written, tested, or changed the student's actual code, backend, or database — "
        "distinguish a stated project fact from your own recommendation, assumption, or suggested "
        "approach.\n\n"
        "Be concise and practical — a few short paragraphs or a short list, not an essay. Use "
        "Markdown where it aids clarity, including tables for anything genuinely tabular (comparing "
        "options field-by-field, a skills breakdown) — they render properly. When you call a tool "
        "that produces cards/tables (search_projects, compare_projects, check_skill_gap, "
        "predict_timeline, generate_milestones, get_learning_path, generate_project_ideas, "
        "refine_project_idea, generate_idea_timeline, generate_idea_milestones), keep your own "
        "reply to a sentence or two of framing — the structured result is shown to the student "
        "directly, so do not re-list it yourself. generate_roadmap/generate_synopsis/"
        "generate_idea_roadmap have no such block — that is where your own Markdown (headings, a "
        "numbered phase list, tables) is exactly what should carry the phases/tasks/sections, using "
        "only the fields the tool actually returned. For generate_project_ideas specifically, "
        "your framing sentence should make clear these are new AI-generated concepts, not existing "
        "catalogue projects."
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


def _active_project_note(selected_project_id: Optional[str]) -> str:
    """Tells the model which project is currently selected, if any, so a
    vague follow-up ('how should I build the backend?') doesn't need the
    student to re-name the project or the model to guess from search history.
    A plain get_project_details lookup — same tool the model itself has, not
    a second source of project data.

    Carries enough of the project's own fields (description, duration,
    skills — not just title/difficulty/domain/technologies) that grounded
    architecture/backend/technology answers don't need a second
    get_project_details round trip just to learn what the project actually
    requires — get_project_details already returns all of this, this just
    stops leaving most of it on the floor."""
    if not selected_project_id:
        return ""
    project, _block = chat_tools.call_tool("get_project_details", {"project_id": selected_project_id})
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
    return (
        f"\n\n[Context — active project: {project['project_id']} \"{project.get('title', '')}\""
        f"{' — ' + description if description else ''}"
        f"{' (' + detail + ')' if detail else ''}]"
    )


def _active_idea_note(selected_idea: Optional[dict[str, Any]]) -> str:
    """Tells the model which GENERATED idea is currently the student's active
    build target, if any — the idea-context mirror of _active_project_note.
    No lookup needed: `selected_idea` already carries the idea's full fields
    (see chat_tools.select_idea), since a generated idea has no catalogue
    record to fetch it back from. Mutually exclusive with an active project
    (see general_reply below), so at most one of these two notes is ever
    non-empty on a given turn.

    Surfaces problem/solution too (select_idea already stores them, this just
    stops leaving them out of the note) — the same "what does this project
    actually require" grounding _active_project_note carries via description,
    just from the idea's own fields instead of a Mongo lookup."""
    name = (selected_idea or {}).get("name") if selected_idea else None
    if not name:
        return ""
    tech = ", ".join((selected_idea.get("technologies") or [])[:5])
    weeks = selected_idea.get("duration_weeks")
    problem = (selected_idea.get("problem") or "").strip()
    solution = (selected_idea.get("solution") or "").strip()
    core = " — ".join(part for part in [f"problem: {problem}" if problem else "", f"solution: {solution}" if solution else ""] if part)
    detail = ", ".join(
        part
        for part in [
            selected_idea.get("difficulty", ""),
            selected_idea.get("domain", ""),
            f"{weeks}wk" if weeks else "",
            tech,
        ]
        if part
    )
    return (
        f"\n\n[Context — active idea (AI-generated, not a catalogue project): \"{name}\""
        f"{' — ' + core if core else ''}"
        f"{' (' + detail + ')' if detail else ''}]"
    )


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
    the assistant. See _create_completion for how they're used."""
    if not config.AI_ASSISTANT_ENABLED:
        return []
    from groq import Groq

    return [Groq(api_key=key) for key in config.GROQ_API_KEYS]


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


def _create_completion(**kwargs: Any):
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
    raise last_error  # every configured key is rate-limited, too-large, or failing


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
    history: Optional[list[dict[str, Any]]], *, with_shown_projects: bool = False
) -> list[dict[str, str]]:
    """Caller-supplied turns, trimmed and validated to role/content shape.

    Shared by `reply()` and `general_reply()` — neither endpoint keeps a
    server-side session for the *model call itself*; both are handed the
    running conversation and just replay it, capped so a long chat can't
    grow the request without bound.

    `with_shown_projects` appends a shown-projects/shown-ideas note (see
    `_shown_projects_note`/`_shown_ideas_note`) — used only by
    `general_reply()`, which is the one entry point where a stored turn can
    carry `blocks`. Only the MOST RECENT turn of each kind gets its note
    replayed, not every one in the trimmed window: once a fresh batch of
    projects or ideas is shown, that's the current set the student is
    looking at (Ideate.jsx's own mergeIdea replaces the grid the same way on
    a new batch) — older ones are superseded, not additive context. Without
    this cap, a conversation that searches or generates ideas more than
    once keeps replaying every earlier turn's full note (per-idea
    problem/solution/unique_point text, for every idea, every time) on every
    later turn — unbounded growth that has driven a real request over a
    model's tokens-per-minute budget (a 413 from Groq, not a flaky rate
    limit — retrying an identical oversized request fails identically).
    """
    trimmed = (history or [])[-MAX_HISTORY_MESSAGES:]

    last_projects_index: Optional[int] = None
    last_ideas_index: Optional[int] = None
    if with_shown_projects:
        for i, turn in enumerate(trimmed):
            if turn.get("role") != "assistant":
                continue
            blocks = turn.get("blocks") or []
            if any(b.get("type") == "project_recommendations" for b in blocks):
                last_projects_index = i
            if any(b.get("type") == "generated_project_ideas" for b in blocks):
                last_ideas_index = i

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
        messages.append({"role": role, "content": content})
    return messages


def _complete(messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> str:
    completion = _create_completion(
        model=config.GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
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


def reply(doc: dict[str, Any], message: str, history: Optional[list[dict[str, str]]] = None) -> str:
    """One assistant reply, grounded in `doc`, given the running `history`."""
    messages = [_system_message(doc), *_history_messages(history), {"role": "user", "content": message[:MAX_MESSAGE_CHARS]}]
    return _complete(messages, temperature=0.4, max_tokens=600)


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
    """
    if not config.AI_ASSISTANT_ENABLED:
        raise AssistantUnavailable("GROQ_API_KEY is not configured.")

    messages: list[dict[str, Any]] = [
        _GENERAL_SYSTEM_MESSAGE,
        *_history_messages(history, with_shown_projects=True),
        {
            "role": "user",
            "content": (
                message[:MAX_MESSAGE_CHARS]
                + _active_project_note(selected_project_id)
                + _active_idea_note(selected_idea)
                + _resume_context_note(resume_skills)
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
