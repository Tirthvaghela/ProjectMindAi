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
    """Assign each member the project role they're the strongest fit for.

    Greedy by input order: each member claims their best-scoring role among
    roles still open, falling back through their weaker categories, then to
    any open role, then to a shared "Supporting / QA" bucket once every role
    is taken (a team larger than the module count is expected to happen).
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

    claimed: set[str] = set()
    assignments = []
    for member in named_members:
        scores = _member_category_scores(member["skills"])
        ranked = sorted(scores.items(), key=lambda kv: kv[1][0], reverse=True)
        # Their single strongest category, even if this project has no open role
        # in it — used below so a fallback assignment still explains itself.
        strongest_category, strongest_skills = (ranked[0][0], ranked[0][1][1]) if ranked and ranked[0][1][0] > 0 else (None, [])

        chosen_role, chosen_category, matched_skills = None, None, []
        for category, (score, matched) in ranked:
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
            matched_skills = strongest_skills

        claimed.add(chosen_role)
        assignments.append(
            {
                "member": member["name"],
                "assigned_role": chosen_role,
                "category": chosen_category,
                "matched_skills": matched_skills,
                "fallback": fallback,
                "strongest_category": strongest_category if fallback else None,
            }
        )

    unfilled_roles = [r["module"] for r in roles if r["module"] not in claimed]

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title"),
        "roles": [r["module"] for r in roles],
        "assignments": assignments,
        "unfilled_roles": unfilled_roles,
    }
