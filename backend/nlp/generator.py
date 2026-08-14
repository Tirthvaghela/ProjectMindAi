"""Template-based synopsis and roadmap generation.

Deliberately not LLM-backed: every other derived feature in this codebase
(skill_gap, check_uniqueness, explain) is a deterministic function over the
project's own fields, with no external API, no cost per call, and no way to
hallucinate a technology the project doesn't actually use. This module keeps
that property. The output reads as a first draft a student edits, not a
finished document — that is the right ambition for a template generator.

Each domain gets a short profile (its typical "core" build phase and the
modules a project in that domain usually has); everything else is assembled
from the project's own title, description, technologies, skills and duration.
"""

from __future__ import annotations

from typing import Any, Optional

from db.schema import DIFFICULTIES, DOMAINS

# domain -> (core phase name, one-line focus, typical modules)
_DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "Artificial Intelligence": {
        "core_phase": "Model Development & Training",
        "core_focus": "building and training the AI model at the project's core",
        "modules": [
            "Data Collection & Preprocessing", "Feature Engineering", "Model Training",
            "Model Evaluation", "Inference API", "User Interface",
        ],
    },
    "Machine Learning": {
        "core_phase": "Model Training & Evaluation",
        "core_focus": "training and evaluating the machine learning model",
        "modules": [
            "Data Preprocessing", "Model Training", "Model Evaluation",
            "Inference API", "Results Dashboard",
        ],
    },
    "Deep Learning": {
        "core_phase": "Neural Network Design & Training",
        "core_focus": "designing and training the neural network architecture",
        "modules": [
            "Dataset Preparation", "Network Architecture Design", "Training Pipeline",
            "Model Evaluation", "Deployment Interface",
        ],
    },
    "Natural Language Processing": {
        "core_phase": "Language Model Development",
        "core_focus": "building the text-understanding pipeline",
        "modules": [
            "Text Preprocessing", "Embedding / Model Pipeline", "Inference Service",
            "Result Presentation Layer",
        ],
    },
    "Computer Vision": {
        "core_phase": "Vision Model Development",
        "core_focus": "building the image/video model pipeline",
        "modules": [
            "Image Acquisition & Preprocessing", "Model Training / Inference",
            "Detection or Classification Pipeline", "Visualization Layer",
        ],
    },
    "Data Science": {
        "core_phase": "Data Analysis & Modelling",
        "core_focus": "analysing the data and building the statistical model",
        "modules": [
            "Data Ingestion", "Exploratory Data Analysis", "Statistical / ML Modelling",
            "Dashboard & Reporting",
        ],
    },
    "Web Development": {
        "core_phase": "Backend & Frontend Development",
        "core_focus": "building the application's backend and user interface",
        "modules": [
            "Authentication", "Backend API", "Database Layer", "Frontend UI", "Deployment",
        ],
    },
    "Mobile Development": {
        "core_phase": "Mobile App Development",
        "core_focus": "building the mobile application screens and logic",
        "modules": [
            "UI/UX Screens", "Local Storage", "Backend Integration",
            "Push Notifications", "App Packaging",
        ],
    },
    "Internet of Things": {
        "core_phase": "Firmware & Sensor Integration",
        "core_focus": "integrating the sensors and device firmware",
        "modules": [
            "Sensor Interfacing", "Microcontroller Firmware", "Connectivity Layer (MQTT/HTTP)",
            "Cloud Dashboard", "Alerting",
        ],
    },
    "Blockchain": {
        "core_phase": "Smart Contract Development",
        "core_focus": "writing and deploying the smart contract logic",
        "modules": [
            "Smart Contract Design", "Contract Testing & Deployment", "Wallet Integration",
            "Frontend DApp", "Transaction Monitoring",
        ],
    },
    "Cybersecurity": {
        "core_phase": "Detection & Defence Engine",
        "core_focus": "building the detection and response logic",
        "modules": [
            "Threat Detection Logic", "Logging & Alerting", "Dashboard", "Response Automation",
        ],
    },
    "Cloud & DevOps": {
        "core_phase": "Pipeline & Infrastructure Automation",
        "core_focus": "automating the build, deploy and monitoring pipeline",
        "modules": [
            "CI/CD Pipeline", "Infrastructure as Code", "Monitoring & Logging",
            "Deployment Automation",
        ],
    },
    "Augmented & Virtual Reality": {
        "core_phase": "Immersive Scene Development",
        "core_focus": "building the 3D scene and interaction logic",
        "modules": [
            "3D Asset Design", "Scene Interaction Logic", "Device / SDK Integration",
            "Performance Optimisation",
        ],
    },
    "Robotics": {
        "core_phase": "Control & Navigation System",
        "core_focus": "building the control and navigation system",
        "modules": [
            "Sensor Fusion", "Control Algorithm", "Navigation / Path Planning",
            "Hardware Interface",
        ],
    },
}

_DEFAULT_PROFILE = {
    "core_phase": "Core Feature Development",
    "core_focus": "building the project's core functionality",
    "modules": ["Core Logic", "Data Layer", "User Interface", "Testing"],
}


def _profile(domain: str) -> dict[str, Any]:
    return _DOMAIN_PROFILES.get(domain, _DEFAULT_PROFILE)


def domain_profile(domain: str) -> dict[str, Any]:
    """Public accessor for a domain's core phase / focus / modules.

    Used outside this module by nlp/team_builder.py, which turns the same
    module breakdown into roles for a team to split up.
    """
    return _profile(domain)


def _article(word: str) -> str:
    """'a' or 'an' for the word that follows — domain and difficulty names vary."""
    return "an" if word[:1].lower() in "aeiou" else "a"


def _first_clause(description: str, max_chars: int = 160) -> str:
    """First sentence of the description, trimmed for use inside a template."""
    text = (description or "").strip()
    for sep in (". ", "! ", "? "):
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    text = text.rstrip(".")
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;: ") + "…"
    return text


def _phase_plan(duration_weeks: float, domain: str) -> list[dict[str, Any]]:
    """Split duration_weeks across a 7-phase plan, the last domain-specific phases
    weighted toward the profile's core phase.

    Rounded to the nearest half-week per phase, then the last phase absorbs any
    rounding remainder so the total always equals duration_weeks exactly —
    *except* for a project short enough that a 0.5-week floor on every phase
    would itself overshoot the total (7 phases x 0.5 = 3.5 weeks minimum), in
    which case phases are split proportionally instead, unrounded.
    """
    profile = _profile(domain)
    template = [
        ("Requirement Analysis", 0.08, "Define objectives, gather requirements and finalise the technology stack."),
        ("System & Data Design", 0.12, "Design the architecture, data model and (if applicable) the dataset pipeline."),
        (profile["core_phase"], 0.30, f"Focus phase: {profile['core_focus']}."),
        ("Application Layer Development", 0.20, "Build the surrounding backend/frontend that exposes the core to a user."),
        ("Integration", 0.10, "Connect the core module with the application layer end-to-end."),
        ("Testing & Evaluation", 0.12, "Test functionality and evaluate results against the project's success criteria."),
        ("Documentation & Deployment", 0.08, "Write up the report/synopsis and deploy or package the final system."),
    ]

    weeks = duration_weeks or 1
    use_half_week_floor = weeks >= len(template) * 0.5

    phases = []
    allocated = 0.0
    for index, (name, weight, description) in enumerate(template):
        is_last = index == len(template) - 1
        if is_last:
            phase_weeks = round(weeks - allocated, 2)
        elif use_half_week_floor:
            phase_weeks = max(0.5, round(weeks * weight * 2) / 2)
        else:
            phase_weeks = round(weeks * weight, 2)
        if not is_last:
            allocated += phase_weeks
        phases.append({"phase": name, "description": description, "weeks": phase_weeks})

    # The half-week floor on every earlier phase can, for a handful of
    # specific durations (duration_weeks=4 is the smallest), consume the
    # whole budget before the last phase — whatever's left over — gets any
    # of its own, landing it at exactly 0 weeks. Whenever that happens, at
    # least one earlier phase must be sitting above its own 0.5 floor (six
    # phases floored at 0.5 each sum to 3.0, below the 3.5-week minimum for
    # this branch), so borrowing 0.5 from the largest one is always safe —
    # it can't go below 0.5 itself — and keeps the total equal to
    # duration_weeks exactly, same as every other duration already does.
    if use_half_week_floor and phases[-1]["weeks"] <= 0:
        donor = max(phases[:-1], key=lambda p: p["weeks"])
        donor["weeks"] = round(donor["weeks"] - 0.5, 2)
        phases[-1]["weeks"] = 0.5

    return phases


def phase_plan(duration_weeks: float, domain: str) -> list[dict[str, Any]]:
    """Public accessor for the phase split — nlp/timeline.py reuses this to
    re-plan phases against a personalised (not just the baseline) duration.

    Deliberately lean (phase/description/weeks only, no per-phase task
    detail) — timeline.predict()'s job is "how long will this take", not
    "what exactly do I build"; see _implementation_detail() below for the
    richer breakdown roadmap_for() layers on top for that second question.
    """
    return _phase_plan(duration_weeks, domain)


def _implementation_detail(phases: list[dict[str, Any]], doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Adds objective/tasks/technologies/expected_output/dependencies to an
    already-computed phase list, turning a timeline into an actionable build
    plan.

    Grounded entirely in this project's own technologies/skills/title and its
    domain profile's real modules (_profile()) — never invented. Matches each
    phase by its own template name, which is always one of the seven fixed
    names _phase_plan() produces (the middle one being the domain's own
    core_phase), so this works for any phase list that function returns.
    """
    technologies = doc.get("technologies") or []
    skills = doc.get("skills") or []
    title = doc.get("title") or "this project"
    profile = _profile(doc.get("domain", ""))
    core_phase_name = profile["core_phase"]

    detailed: list[dict[str, Any]] = []
    previous_name: Optional[str] = None
    for phase in phases:
        name = phase["phase"]
        phase_tech: list[str] = []
        output = ""

        if name == "Requirement Analysis":
            tasks = [
                f'Define the problem "{title}" solves and its success criteria.',
                f"Finalise the technology stack: {', '.join(technologies[:5]) or 'to be confirmed'}.",
            ]
            output = "A written requirements brief and a confirmed technology stack."
        elif name == "System & Data Design":
            tasks = [
                "Design the overall architecture: modules, data flow, and how they connect.",
                f"Plan the inputs/data the {core_phase_name.lower()} phase will need.",
            ]
            output = "An architecture/data-design document the remaining phases follow."
        elif name == core_phase_name:
            tasks = [f"Implement: {module}." for module in profile["modules"]]
            phase_tech = technologies
            output = f"A working {core_phase_name.lower()} — {profile['core_focus']}."
        elif name == "Application Layer Development":
            tasks = [
                "Build the backend/API layer that exposes the core module to a client.",
                "Build the user-facing interface on top of it.",
            ]
            phase_tech = technologies
            output = "A backend/frontend layer that exposes the core to a user."
        elif name == "Integration":
            tasks = [
                f"Connect the {core_phase_name.lower()} output to the application layer end-to-end.",
                "Resolve any interface mismatches between modules.",
            ]
            output = "The core and application layers working together as one system."
        elif name == "Testing & Evaluation":
            tasks = [
                f"Test against the project's required skills: {', '.join(skills[:3]) or 'core functionality'}.",
                "Evaluate results against the success criteria defined in Requirement Analysis.",
            ]
            output = "A tested system with a documented evaluation."
        elif name == "Documentation & Deployment":
            tasks = ["Write up the synopsis/report.", "Deploy or package the final system."]
            output = "A deployed/packaged system with accompanying documentation."
        else:
            # Unreachable with _phase_plan()'s own fixed template, but a
            # future/custom phase list should degrade to "no detail" rather
            # than crash or invent something.
            tasks = []

        detailed.append(
            {
                **phase,
                "objective": phase["description"],
                "tasks": tasks,
                "technologies": phase_tech,
                "expected_output": output,
                "dependencies": [previous_name] if previous_name else [],
            }
        )
        previous_name = name

    return detailed


def roadmap_for(doc: dict[str, Any]) -> dict[str, Any]:
    """A phase-by-phase development roadmap sized to the project's duration.

    Each phase carries not just a name/weeks/description but an actionable
    objective, tasks, the technologies it touches, its expected output, and
    which earlier phase it depends on (see _implementation_detail()) — so
    "create a roadmap" and "give me the implementation plan" are the same
    generator, not two competing ones.
    """
    duration_weeks = doc.get("duration_weeks") or 1
    phases = _phase_plan(duration_weeks, doc.get("domain", ""))
    phases = _implementation_detail(phases, doc)
    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title"),
        "total_weeks": duration_weeks,
        "phases": phases,
    }


def milestones_from_phases(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One measurable milestone per phase, marking the cumulative week it
    should be complete by — derived directly from an existing phase list
    (roadmap_for()'s or timeline.predict()'s) so a milestone can never
    disagree with the phases/timeline it describes. Not a second planning
    computation: every number here is just a running sum of `weeks` values
    the caller already computed.
    """
    cumulative = 0.0
    milestones = []
    for index, phase in enumerate(phases, start=1):
        cumulative += phase["weeks"]
        milestones.append(
            {
                "id": f"M{index}",
                "title": f"{phase['phase']} completed",
                "phase": phase["phase"],
                "week": round(cumulative, 2),
            }
        )
    return milestones


def milestones_for(doc: dict[str, Any]) -> dict[str, Any]:
    """Measurable milestones for a project's baseline roadmap."""
    roadmap = roadmap_for(doc)
    return {
        "project_id": roadmap["project_id"],
        "title": roadmap["title"],
        "total_weeks": roadmap["total_weeks"],
        "milestones": milestones_from_phases(roadmap["phases"]),
    }


def synopsis_for(doc: dict[str, Any]) -> dict[str, Any]:
    """A first-draft project synopsis assembled from the project's own fields."""
    title = doc.get("title", "")
    description = doc.get("description", "")
    domain = doc.get("domain", "")
    difficulty = (doc.get("difficulty") or "").lower()
    technologies = doc.get("technologies", [])
    skills = doc.get("skills", [])
    duration_weeks = doc.get("duration_weeks") or 1
    profile = _profile(domain)
    lead_tech = ", ".join(technologies[:4]) + (" and others" if len(technologies) > 4 else "")

    abstract = (
        f"{description} This {difficulty}-level {domain} project is built using "
        f"{lead_tech or 'a modern technology stack'}, with an estimated completion "
        f"time of {duration_weeks} week{'s' if duration_weeks != 1 else ''}."
    ).strip()

    problem_statement = (
        f"Students exploring {domain} often lack a ready-made, working example of: "
        f"{_first_clause(description)}. \"{title}\" is proposed to close that gap by "
        f"combining {', '.join(technologies[:3]) or 'the required tools'} into one "
        f"working system, rather than leaving the idea at the concept stage."
    )

    objectives = [
        f"Design and implement {_article(domain)} {domain.lower()} system that addresses: "
        f"{_first_clause(description, 100)}.",
        f"Apply {', '.join(technologies[:3]) or 'the chosen stack'} together in a single integrated build.",
    ]
    if skills:
        objectives.append(f"Build and demonstrate proficiency in {', '.join(skills[:4])}.")
    objectives.append("Evaluate the finished system against a clear, stated success criterion.")
    objectives.append("Document the design, implementation and results for academic submission.")

    scope = (
        f"Scoped for {_article(difficulty)} {difficulty} student working individually over "
        f"{duration_weeks} week{'s' if duration_weeks != 1 else ''}. Covers {profile['core_phase'].lower()} "
        f"plus the surrounding application layer; does not cover production-scale "
        f"deployment, load handling, or long-term maintenance."
    )

    phases = _phase_plan(duration_weeks, domain)
    methodology = [p["phase"] for p in phases]

    expected_results = [
        f"A working {domain.lower()} application demonstrating {profile['core_focus']}.",
        f"Demonstrated integration of {', '.join(technologies[:3]) or 'the chosen stack'} in one system.",
        "A documented evaluation (accuracy, performance, or usability, as appropriate to the project) in the final report.",
    ]

    future_scope = [
        f"Extend the {profile['core_phase'].lower()} with more advanced techniques as skills grow.",
        "Add authentication and multi-user support for a real-world deployment.",
    ]
    if domain not in ("Mobile Development",):
        future_scope.append("Package the application as a mobile companion app.")
    if domain not in ("Cloud & DevOps",):
        future_scope.append("Set up a CI/CD pipeline for automated testing and deployment.")

    return {
        "project_id": doc.get("project_id"),
        "title": title,
        "abstract": abstract,
        "problem_statement": problem_statement,
        "objectives": objectives,
        "scope": scope,
        "methodology": methodology,
        "modules": profile["modules"],
        "technology_stack": technologies,
        "expected_results": expected_results,
        "future_scope": future_scope,
    }


def _idea_weeks(duration_weeks: Optional[int]) -> int:
    try:
        return max(1, min(int(duration_weeks), 24)) if duration_weeks is not None else 8
    except (TypeError, ValueError):
        return 8


def idea_doc(
    name: str,
    domain: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    difficulty: Optional[str] = None,
    technologies: Optional[list[str]] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """A synthetic project-shaped doc from a GENERATED idea's own fields, fed
    to the exact same generator/timeline/skill_gap functions a catalogue
    project's project_id would resolve to via Mongo — a generated idea just
    has no project_id to look up, so this stands in for the lookup. Shared by
    every idea-scoped tool/route (nlp/chat_tools.py's generate_idea_* tools,
    routes/ideas.py's REST endpoints) so they all build the doc the same way.

    `skills` mirrors `technologies` rather than staying empty: a generated
    idea has no separate skills taxonomy distinct from its tech stack (unlike
    a catalogue project's curated "skills" list), so technologies is the
    honest stand-in — the same substitution the assistant's own idea-context
    notes already lean on (see nlp/ai_assistant.py's _idea_detail_note).
    `description` defaults to "" (fine for roadmap/timeline/milestones, which
    never read it) but should be passed — typically f"{problem} {solution}"
    — for synopsis_for(), whose abstract/problem_statement need real prose.
    """
    tech = [t.strip() for t in (technologies or []) if isinstance(t, str) and t.strip()]
    return {
        "project_id": None,
        "title": name,
        "description": (description or "").strip(),
        "domain": domain if domain in DOMAINS else "",
        "difficulty": difficulty if difficulty in DIFFICULTIES else "",
        "duration_weeks": _idea_weeks(duration_weeks),
        "technologies": tech,
        "skills": tech,
    }
