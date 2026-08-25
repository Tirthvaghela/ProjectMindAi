"""Team role suggestion — splits a project into roles and assigns each team
member to the role they're the best fit for, based on the skills they list.

Roles come straight from the project's own module breakdown
(nlp/generator.py's domain profiles), so a team building a Blockchain project
sees "Smart Contract Design", not a generic "Backend" bucket. Matching a
member's skills to a role's category is deliberately simple keyword matching
rather than another embedding call — there is no ranking to get right here,
just a legible "why this person, this role" a team can sanity-check at a
glance.
"""

from __future__ import annotations

from typing import Any

from nlp.generator import domain_profile

# Every module string used across nlp/generator.py's domain profiles maps to
# exactly one category here — that mapping is what lets a member's skills be
# matched to a role.
_MODULE_CATEGORY: dict[str, str] = {
    "Data Collection & Preprocessing": "Data / ML",
    "Feature Engineering": "Data / ML",
    "Model Training": "Data / ML",
    "Model Evaluation": "Data / ML",
    "Inference API": "Backend",
    "User Interface": "Frontend / UI",
    "Data Preprocessing": "Data / ML",
    "Results Dashboard": "Frontend / UI",
    "Dataset Preparation": "Data / ML",
    "Network Architecture Design": "Data / ML",
    "Training Pipeline": "Data / ML",
    "Deployment Interface": "DevOps",
    "Text Preprocessing": "Data / ML",
    "Embedding / Model Pipeline": "Data / ML",
    "Inference Service": "Backend",
    "Result Presentation Layer": "Frontend / UI",
    "Image Acquisition & Preprocessing": "Data / ML",
    "Model Training / Inference": "Data / ML",
    "Detection or Classification Pipeline": "Data / ML",
    "Visualization Layer": "Frontend / UI",
    "Data Ingestion": "Data / ML",
    "Exploratory Data Analysis": "Data / ML",
    "Statistical / ML Modelling": "Data / ML",
    "Dashboard & Reporting": "Frontend / UI",
    "Authentication": "Backend",
    "Backend API": "Backend",
    "Database Layer": "Backend",
    "Frontend UI": "Frontend / UI",
    "Deployment": "DevOps",
    "UI/UX Screens": "Frontend / UI",
    "Local Storage": "Backend",
    "Backend Integration": "Backend",
    "Push Notifications": "Backend",
    "App Packaging": "DevOps",
    "Sensor Interfacing": "Hardware / IoT",
    "Microcontroller Firmware": "Hardware / IoT",
    "Connectivity Layer (MQTT/HTTP)": "Backend",
    "Cloud Dashboard": "Frontend / UI",
    "Alerting": "Backend",
    "Smart Contract Design": "Blockchain",
    "Contract Testing & Deployment": "Testing / QA",
    "Wallet Integration": "Blockchain",
    "Frontend DApp": "Frontend / UI",
    "Transaction Monitoring": "Backend",
    "Threat Detection Logic": "Security",
    "Logging & Alerting": "Backend",
    "Dashboard": "Frontend / UI",
    "Response Automation": "Security",
    "CI/CD Pipeline": "DevOps",
    "Infrastructure as Code": "DevOps",
    "Monitoring & Logging": "DevOps",
    "Deployment Automation": "DevOps",
    "3D Asset Design": "Frontend / UI",
    "Scene Interaction Logic": "Frontend / UI",
    "Device / SDK Integration": "Backend",
    "Performance Optimisation": "Backend",
    "Sensor Fusion": "Hardware / IoT",
    "Control Algorithm": "Data / ML",
    "Navigation / Path Planning": "Data / ML",
    "Hardware Interface": "Hardware / IoT",
    "Core Logic": "Backend",
    "Data Layer": "Backend",
    "Testing": "Testing / QA",
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Data / ML": [
        "python", "machine learning", "deep learning", "data", "model", "pandas", "numpy",
        "tensorflow", "pytorch", "scikit", "sklearn", "nlp", "computer vision", "statistics",
        "analytics", "algorithm",
    ],
    "Frontend / UI": [
        "react", "vue", "angular", "frontend", "html", "css", "javascript", "typescript",
        "ui", "ux", "design", "figma", "tailwind",
    ],
    "Backend": [
        "backend", "api", "server", "flask", "django", "node", "express", "database",
        "sql", "mongodb", "rest", "microservice",
    ],
    "DevOps": [
        "docker", "kubernetes", "ci/cd", "cicd", "aws", "azure", "gcp", "cloud",
        "devops", "deployment", "linux", "terraform",
    ],
    "Testing / QA": [
        "test", "testing", "qa", "quality assurance", "debugging", "pytest", "junit",
    ],
    "Hardware / IoT": [
        "sensor", "firmware", "arduino", "raspberry", "iot", "embedded", "circuit",
    ],
    "Blockchain": [
        "blockchain", "solidity", "smart contract", "web3", "ethereum", "crypto",
    ],
    "Security": [
        "security", "cyber", "encryption", "penetration", "vulnerability", "firewall",
    ],
}


def category_for(module: str) -> str:
    """Public accessor for _MODULE_CATEGORY, so other callers (nlp/feasibility.py's
    team-size/role estimates) read the exact same module -> category mapping
    this file's own suggest_roles() uses, rather than a second table."""
    return _MODULE_CATEGORY.get(module, "General")


def _member_category_scores(skills: list[str]) -> dict[str, tuple[float, list[str]]]:
    """category -> (score, matching skill strings) for one member's skill list."""
    scores: dict[str, tuple[float, list[str]]] = {c: (0.0, []) for c in _CATEGORY_KEYWORDS}
    for skill in skills:
        skill_l = skill.lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in skill_l for kw in keywords):
                score, matched = scores[category]
                scores[category] = (score + 1.0, matched + [skill])
    return scores


def suggest_roles(doc: dict[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
    """Assign every project role to a member of this exact team.

    This team is fixed — there's no invite flow behind it, so a module that
    outnumbers the people listed will never get a third person to claim it.
    Two passes, both greedy by input order:

    1. Each member claims their own best-scoring open role, falling back
       through weaker categories, then any open role, then a shared
       "Supporting / QA" bucket once every role is taken (a team larger than
       the module count is expected to happen).
    2. Any module still open after that (more modules than members) is
       handed to whichever member scores best against it, ties going to
       whoever is carrying the fewest roles so far — so a team of 2 still
       ends up owning all 4 modules instead of leaving 2 "unassigned".
    """
    profile = domain_profile(doc.get("domain", ""))
    roles = [
        {"module": name, "category": _MODULE_CATEGORY.get(name, "General")}
        for name in profile["modules"]
    ]

    named_members = [
        {"name": (m.get("name") or "").strip() or f"Member {i + 1}", "skills": m.get("skills") or []}
        for i, m in enumerate(members)
    ]

    member_scores: list[dict[str, tuple[float, list[str]]]] = []
    ranked_scores: list[list[tuple[str, tuple[float, list[str]]]]] = []
    strongest: list[tuple[str | None, list[str]]] = []
    for member in named_members:
        scores = _member_category_scores(member["skills"])
        ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
        member_scores.append(scores)
        ranked_scores.append(ranked)
        # Their single strongest category, even if this project has no open role
        # in it — used below so a fallback assignment still explains itself.
        strongest.append((ranked[0][0], ranked[0][1][1]) if ranked and ranked[0][1][0] > 0 else (None, []))

    claimed: set[str] = set()
    role_count = [0] * len(named_members)
    assignments: list[dict[str, Any]] = []

    def _assign(i: int, module: str, category: str, matched_skills: list[str], fallback: bool) -> None:
        claimed.add(module)
        role_count[i] += 1
        assignments.append(
            {
                "member": named_members[i]["name"],
                "assigned_role": module,
                "category": category,
                "matched_skills": matched_skills,
                "fallback": fallback,
                "strongest_category": strongest[i][0] if fallback else None,
            }
        )

    # Pass 1 — each member's own best-fit role.
    for i in range(len(named_members)):
        chosen_role, chosen_category, matched_skills = None, None, []
        for category, (score, matched) in ranked_scores[i]:
            if score <= 0:
                break
            candidates = [r for r in roles if r["category"] == category and r["module"] not in claimed]
            if candidates:
                chosen_role, chosen_category, matched_skills = candidates[0]["module"], category, matched
                break

        fallback = chosen_role is None
        if fallback:
            open_roles = [r for r in roles if r["module"] not in claimed]
            if open_roles:
                chosen_role, chosen_category = open_roles[0]["module"], open_roles[0]["category"]
            else:
                chosen_role, chosen_category = "Supporting / QA", "General"
            # Still show what they're actually strong at, even though this
            # project has no open role for it — an empty list here would read
            # as "no skills", not "no matching role".
            matched_skills = strongest[i][1]

        _assign(i, chosen_role, chosen_category, matched_skills, fallback)

    # Pass 2 — modules pass 1 left open (more modules than members) still
    # need a real owner, since nobody new is joining to take them.
    for role in [r for r in roles if r["module"] not in claimed]:
        best_i, best_score, best_matched = 0, -1.0, []
        for i in range(len(named_members)):
            score, matched = member_scores[i][role["category"]]
            if (score, -role_count[i]) > (best_score, -role_count[best_i]):
                best_i, best_score, best_matched = i, score, matched
        fallback = best_score <= 0
        matched_skills = best_matched if not fallback else strongest[best_i][1]
        _assign(best_i, role["module"], role["category"], matched_skills, fallback)

    # Group each member's cards together (primary role first, then any extra
    # roles picked up in pass 2) instead of interleaving by pass.
    order = {m["name"]: i for i, m in enumerate(named_members)}
    assignments.sort(key=lambda a: order[a["member"]])

    unfilled_roles = [r["module"] for r in roles if r["module"] not in claimed]

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title"),
        "roles": [r["module"] for r in roles],
        "assignments": assignments,
        "unfilled_roles": unfilled_roles,
    }
