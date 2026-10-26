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

import re
from typing import Any, Optional

from nlp import skills as skill_names
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


_UNASSIGNED_MESSAGES = {
    "no_skills": "No skills recorded yet — add skills to get a role suggestion.",
    "unrecognised_skills": "None of the listed skills map to a role area on this project.",
    "no_role_in_area": "This project has no role in their strongest area.",
    "roles_taken": "Every role in their area is already taken by a stronger match.",
}


def _normalised_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per real person: blank names get a placeholder, skills are
    trimmed and de-duplicated, and a roster that lists the same person twice
    (same `id` when the caller has one, otherwise the same name ignoring
    case) is merged instead of producing duplicate recommendations."""
    merged: dict[str, dict[str, Any]] = {}
    for i, member in enumerate(members):
        name = (member.get("name") or "").strip() or f"Member {i + 1}"
        key = str(member["id"]) if member.get("id") else name.casefold()
        entry = merged.setdefault(key, {"name": name, "skills": []})
        seen = {s.casefold() for s in entry["skills"]}
        for skill in member.get("skills") or []:
            if isinstance(skill, str) and skill.strip() and skill.strip().casefold() not in seen:
                entry["skills"].append(skill.strip())
                seen.add(skill.strip().casefold())
    return list(merged.values())


def suggest_roles(doc: dict[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
    """Match each member to at most one of this project's roles, from the
    skills they actually list.

    Every (member, role) pair whose category the member has skills in is
    scored by how many of their skills match that category, and pairs are
    taken best-score-first — so the member with the strongest claim on a
    role gets it, not whoever happens to be listed first. A member holds one
    role and a role has one owner. Nothing is assigned to fill a seat:

    - a role nobody fits stays in `unfilled_roles`;
    - a member with no fitting role (no skills listed, skills that map to no
      role area, an area this project has no role in, or every role in their
      area already taken) is reported in `unassigned_members` with the
      reason, rather than being handed an unrelated role.
    """
    profile = domain_profile(doc.get("domain", ""))
    roles = [
        {"module": name, "category": _MODULE_CATEGORY.get(name, "General")}
        for name in profile["modules"]
    ]
    named_members = _normalised_members(members)

    member_scores = [_member_category_scores(m["skills"]) for m in named_members]
    role_categories = {r["category"] for r in roles}

    pairs: list[tuple[float, int, int]] = []
    for i, scores in enumerate(member_scores):
        for j, role in enumerate(roles):
            score = scores.get(role["category"], (0.0, []))[0]
            if score > 0:
                pairs.append((-score, i, j))
    pairs.sort()

    role_of_member: dict[int, int] = {}
    claimed: set[int] = set()
    for _, i, j in pairs:
        if i in role_of_member or j in claimed:
            continue
        role_of_member[i] = j
        claimed.add(j)

    assignments: list[dict[str, Any]] = []
    unassigned: list[dict[str, Any]] = []
    for i, member in enumerate(named_members):
        ranked = sorted(member_scores[i].items(), key=lambda kv: kv[1][0], reverse=True)
        strongest = ranked[0][0] if ranked and ranked[0][1][0] > 0 else None

        if i in role_of_member:
            role = roles[role_of_member[i]]
            assignments.append(
                {
                    "member": member["name"],
                    "assigned_role": role["module"],
                    "category": role["category"],
                    "matched_skills": member_scores[i][role["category"]][1],
                    "fallback": False,
                    "strongest_category": None,
                }
            )
            continue

        if not member["skills"]:
            reason = "no_skills"
        elif strongest is None:
            reason = "unrecognised_skills"
        elif not any(member_scores[i][c][0] > 0 for c in role_categories):
            reason = "no_role_in_area"
        else:
            reason = "roles_taken"
        unassigned.append(
            {
                "member": member["name"],
                "reason": reason,
                "message": _UNASSIGNED_MESSAGES[reason],
                "strongest_category": strongest,
                "skills": member["skills"],
            }
        )

    return {
        "project_id": doc.get("project_id"),
        "title": doc.get("title"),
        "roles": [r["module"] for r in roles],
        "assignments": assignments,
        "unassigned_members": unassigned,
        "unfilled_roles": [r["module"] for j, r in enumerate(roles) if j not in claimed],
    }


# ===========================================================================
# Profile-aware job-role fit
#
# suggest_roles() above answers "which of this project's *modules* should each
# person own", from keyword counts. The functions below answer a different,
# complementary question - "which *job role* does each person's evidence
# support, and does the team cover what the project needs" - using the same
# module->category table for the project's needs and the shared alias layer
# (nlp/skills.py) for skill names. Both run together in teams/service.py:
# team_roles(); suggest_roles() and POST /api/team-builder are unchanged.
#
# Scores are heuristic evidence strength on a 0-100 scale, NOT calibrated
# probabilities: there is no outcome data to calibrate against. They are
# deterministic and bounded, and every component is shown to the user.
# ===========================================================================

_STRONG, _WEAK = 1.0, 0.4

# Self-reported level -> how much a matching skill counts. A skill with no level
# (typed manually, or a technology from a past project) sits between Beginner
# and Intermediate: it is evidence of use, with no claim about depth.
LEVEL_WEIGHT = {"Beginner": 0.5, "Intermediate": 0.8, "Advanced": 1.0}
UNLEVELLED_WEIGHT = 0.6
# Weighted evidence at which the skills component saturates at 1.0 (about three
# solid skills); more evidence cannot push a score past the bound.
SATURATION = 2.5

COMPONENT_WEIGHTS = {"skills": 0.6, "coverage": 0.3, "preference": 0.1}
MIN_SUGGEST_SCORE = 20  # below this there is too little evidence to suggest a role
STRONG_SCORE, MODERATE_SCORE = 65, 40
ALTERNATIVE_MIN_SCORE, ALTERNATIVE_BAND, MAX_ALTERNATIVES = 40, 20, 2

SCORE_MEANING = (
    "A 0-100 heuristic of how much self-reported evidence (skills, weighted by stated level) "
    "supports this role, blended with how many of the project's needs for it the person already "
    "covers and whether they listed it as a preferred role. It is not a probability and not a "
    "measure of verified ability."
)


def _kw(strong: str, weak: str = "") -> dict[str, float]:
    out = {k.strip(): _STRONG for k in strong.split(",") if k.strip()}
    out.update({k.strip(): _WEAK for k in weak.split(",") if k.strip() and k.strip() not in out})
    return out


# Keywords are matched as whole words/phrases against the canonical skill name
# (so "ReactJS" -> "react"), never as substrings - "ui" must not match "build".
ROLE_KEYWORDS: dict[str, dict[str, float]] = {
    "Frontend Developer": _kw(
        "react,vue,angular,svelte,html,css,tailwind css,tailwind,frontend,front-end,next.js,redux,typescript,sass,bootstrap,responsive design",
        "javascript,figma,ui,ux,web development",
    ),
    "Backend Developer": _kw(
        "backend,back-end,api,rest,graphql,flask,django,fastapi,node.js,node,express,spring,spring boot,microservice,php,laravel,java,go,golang,rust,.net,asp.net,authentication",
        "python,javascript,sql,mongodb,postgresql,server",
    ),
    "Full-Stack Developer": {},  # derived from the Frontend and Backend evidence in score_role
    "AI / ML Engineer": _kw(
        "machine learning,deep learning,tensorflow,pytorch,scikit-learn,keras,nlp,natural language processing,computer vision,opencv,transformers,hugging face,neural network,model training,mlops,llm",
        "python,pandas,numpy,statistics,data science,jupyter,matplotlib",
    ),
    "Data Engineer": _kw(
        "etl,airflow,spark,pyspark,kafka,data pipeline,data warehouse,dbt,hadoop,bigquery,snowflake,data engineering",
        "python,sql,pandas,postgresql,data analysis,data",
    ),
    "Database Engineer": _kw(
        "sql,postgresql,mysql,mongodb,database,sqlite,redis,oracle,nosql,schema design,query optimization,data modelling,data modeling",
        "orm,backend",
    ),
    "QA / Test Engineer": _kw(
        "testing,qa,quality assurance,pytest,jest,selenium,cypress,junit,test automation,unit testing,playwright,vitest",
        "debugging,ci/cd",
    ),
    "DevOps Engineer": _kw(
        "docker,kubernetes,ci/cd,terraform,ansible,jenkins,github actions,aws,azure,gcp,linux,devops,nginx,helm,cloud,deployment",
        "bash,git,monitoring,prometheus,grafana",
    ),
    "Mobile Developer": _kw(
        "android,ios,flutter,react native,kotlin,swift,dart,jetpack compose,swiftui,mobile development",
        "java,firebase",
    ),
    "Embedded / IoT Engineer": _kw(
        "arduino,raspberry pi,esp32,embedded,firmware,mqtt,iot,microcontroller,stm32,sensors,c++,rtos",
        "python,c,electronics",
    ),
    "Security Engineer": _kw(
        "security,cybersecurity,penetration testing,encryption,owasp,cryptography,vulnerability,firewall,pentesting",
        "linux,networking,authentication",
    ),
    "Blockchain Developer": _kw(
        "solidity,ethereum,smart contract,smart contracts,blockchain,web3,hardhat,truffle",
        "javascript,cryptography",
    ),
    "UI / UX Designer": _kw(
        "figma,ui/ux,ux design,ui design,wireframing,prototyping,user research,design systems,usability,accessibility,adobe xd,sketch",
        "ui,ux,css,html,design",
    ),
    "Project Coordinator": _kw(
        "project management,scrum,agile,coordination,jira,leadership,planning,trello,team management",
        "communication,documentation",
    ),
    "Researcher / Documentation": _kw(
        "research,technical writing,documentation,literature review,latex,writing",
        "analysis,presentation",
    ),
}

# The existing module categories -> the job role that owns them, so the
# project's needs come from the same module breakdown suggest_roles() uses.
_CATEGORY_ROLE = {
    "Frontend / UI": "Frontend Developer",
    "Backend": "Backend Developer",
    "Data / ML": "AI / ML Engineer",
    "DevOps": "DevOps Engineer",
    "Testing / QA": "QA / Test Engineer",
    "Hardware / IoT": "Embedded / IoT Engineer",
    "Blockchain": "Blockchain Developer",
    "Security": "Security Engineer",
}
_DATABASE_MODULES = {"Database Layer", "Data Layer", "Local Storage"}
# Roles whose need is never inferred from a project's technology list: design,
# coordination and writing are real work but not something a tech stack names.
_NOT_TECH_DRIVEN = {"Full-Stack Developer", "UI / UX Designer", "Project Coordinator", "Researcher / Documentation"}
ROLE_ORDER = list(ROLE_KEYWORDS)  # fixed order = deterministic tie-breaks

_kw_patterns: dict[str, re.Pattern[str]] = {}


def _pattern(keyword: str) -> re.Pattern[str]:
    if keyword not in _kw_patterns:
        _kw_patterns[keyword] = re.compile(r"(?<![a-z0-9+#])" + re.escape(keyword) + r"(?![a-z0-9+#])")
    return _kw_patterns[keyword]


def _skill_text(name: str) -> str:
    return (skill_names.canonical_name(name) or name).lower()


def _keyword_weight(role: str, name: str) -> float:
    """Best keyword weight for `name` under `role` (0.0 = no relevance)."""
    text = _skill_text(name)
    best = 0.0
    for keyword, weight in ROLE_KEYWORDS[role].items():
        if weight > best and _pattern(keyword).search(text):
            best = weight
    return best


def _level_weight(level: Optional[str]) -> float:
    return LEVEL_WEIGHT.get(level, UNLEVELLED_WEIGHT)


def _evidence(role: str, skills: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
    """(weighted evidence, supporting skills strongest-first) for one role."""
    rows = []
    for skill in skills:
        keyword = _keyword_weight(role, skill["name"])
        if keyword:
            rows.append((keyword * _level_weight(skill.get("level")), skill))
    rows.sort(key=lambda r: (-r[0], r[1]["name"].lower()))
    return sum(w for w, _ in rows), [{"name": s["name"], "level": s.get("level")} for _, s in rows]


def _role_needs(role: str, requirements: list[str]) -> list[str]:
    """The project's required skills/technologies this role is responsible for.
    A requirement belongs to every role it is strong evidence for."""
    if role == "Full-Stack Developer":
        return [
            r for r in requirements
            if _keyword_weight("Frontend Developer", r) == _STRONG or _keyword_weight("Backend Developer", r) == _STRONG
        ]
    return [r for r in requirements if _keyword_weight(role, r) == _STRONG]


def _covers(skills: list[dict[str, Any]], requirement: str) -> bool:
    return any(skill_names.same_skill(s["name"], requirement) for s in skills)


def _confidence(score: float) -> str:
    return "strong" if score >= STRONG_SCORE else "moderate" if score >= MODERATE_SCORE else "tentative"


def score_role(
    role: str, skills: list[dict[str, Any]], preferred_roles: list[str], requirements: list[str]
) -> dict[str, Any]:
    """One person's heuristic fit for one role, with every component exposed.

    skills: [{name, level|None}] - self-reported. The score is
    100 * (0.6*skills + 0.3*coverage + 0.1*preference) / (sum of the weights of
    the components that exist for this person), so a missing component (no
    project requirements, no stated preferences) neither helps nor hurts. With
    no matching skill the score is 0 whatever else is true: a preference is a
    wish, not evidence of competence.
    """
    if role == "Full-Stack Developer":
        front, front_rows = _evidence("Frontend Developer", skills)
        back, back_rows = _evidence("Backend Developer", skills)
        # Needs both sides; the weaker side limits the score so one strong
        # front-end skill set plus a single backend tool is not "full-stack".
        balance = min(1.0, min(front, back) / 0.8)
        seen = {r["name"] for r in front_rows}
        rows = front_rows + [r for r in back_rows if r["name"] not in seen]
        skill_component = min(1.0, (front + back) / SATURATION) * balance
    else:
        raw, rows = _evidence(role, skills)
        skill_component = min(1.0, raw / SATURATION)

    needs = _role_needs(role, requirements)
    missing = [n for n in needs if not _covers(skills, n)]
    components = {"skills": skill_component}
    if needs:
        components["coverage"] = (len(needs) - len(missing)) / len(needs)
    if preferred_roles:
        components["preference"] = 1.0 if role in preferred_roles else 0.0

    if skill_component <= 0:
        score = 0.0
    else:
        total = sum(COMPONENT_WEIGHTS[k] for k in components)
        score = 100 * sum(COMPONENT_WEIGHTS[k] * v for k, v in components.items()) / total
    score = round(max(0.0, min(100.0, score)), 1)
    return {
        "role": role,
        "score": score,
        "confidence": _confidence(score),
        "components": {k: round(v, 2) for k, v in components.items()},
        "supporting_skills": rows[:5],
        "missing_skills": missing[:4],
        "preferred": role in preferred_roles,
    }


_ORIGIN = {
    "profile": "their saved profile",
    "profile+manual": "their profile and the skills they entered for this team",
    "manual": "the skills they entered for this team",
}


def _explain(fit: dict[str, Any], member: dict[str, Any], domain: str) -> str:
    skills = fit["supporting_skills"]
    shown = ", ".join(f"{s['name']} ({s['level']})" if s["level"] else s["name"] for s in skills[:3])
    parts = [f"{_ORIGIN[member['source']].capitalize()} lists {shown}, which support {fit['role']}."]
    if any(s["level"] for s in skills[:3]):
        parts.append("Levels are self-reported.")
    if fit["preferred"]:
        parts.append("They also named it a preferred role (a preference, not proof of skill).")
    if member.get("interests") and domain in member["interests"]:
        parts.append(f"They are interested in {domain} projects.")
    if fit["missing_skills"]:
        parts.append(f"The project also needs {', '.join(fit['missing_skills'])}, which they have not listed.")
    return " ".join(parts)


def member_role_fit(member: dict[str, Any], requirements: list[str], domain: str) -> dict[str, Any]:
    """Every role's fit for one member, then the primary suggestion and
    alternatives. Independent of the rest of the team by construction - team
    composition is handled in team_coverage(), so a good individual match is
    never lowered because a teammate matches too."""
    skills, preferred = member["skills"], member.get("preferred_roles") or []
    base = {
        "user_id": member.get("id"),
        "name": member["name"],
        "source": member["source"],
        "profile_status": member.get("profile_status"),
    }
    # Pass-through flags set by teams/service.py: whether the viewer's own profile
    # is shared, and whether a teammate's profile information is unavailable.
    for flag in ("profile_shared", "info_unavailable"):
        if flag in member:
            base[flag] = member[flag]
    if not skills:
        message = (
            "No skills on file yet - complete your profile or add skills for this team to get a suggestion."
            if member["source"] == "none" else "No skills yet."
        )
        if member.get("info_unavailable"):
            message = (
                "No profile information is available for matching - it has not been shared with the team, or "
                "has not been added. That says nothing about what this person can do."
            )
        return {**base, "suggested": None, "alternatives": [], "fits": {}, "message": message}

    fits = {role: score_role(role, skills, preferred, requirements) for role in ROLE_ORDER}
    ranked = sorted(fits.values(), key=lambda f: (-f["score"], ROLE_ORDER.index(f["role"])))
    top = ranked[0]
    if top["score"] < MIN_SUGGEST_SCORE:
        return {**base, "suggested": None, "alternatives": [], "fits": fits,
                "message": "None of their listed skills clearly point to a role area yet."}

    suggested = {**top, "explanation": _explain(top, member, domain)}
    alternatives = [
        {"role": f["role"], "score": f["score"], "confidence": f["confidence"], "supporting_skills": f["supporting_skills"][:3]}
        for f in ranked[1:]
        if f["score"] >= ALTERNATIVE_MIN_SCORE and f["score"] >= top["score"] - ALTERNATIVE_BAND
    ][:MAX_ALTERNATIVES]
    return {**base, "suggested": suggested, "alternatives": alternatives, "fits": fits, "message": None}


def needed_roles(doc: dict[str, Any], requirements: list[str], team_size: int) -> list[dict[str, Any]]:
    """The job roles this project's work calls for, most important first.

    From the same module breakdown suggest_roles() uses, plus any role the
    project's own technologies are strong evidence for. Only the top
    max(2, team_size) are `priority`: a two-person team is not told it has a
    coverage gap in every specialty.
    """
    counts: dict[str, int] = {}
    for module in domain_profile(doc.get("domain", ""))["modules"]:
        if module in _DATABASE_MODULES:
            role = "Database Engineer"
        else:
            role = _CATEGORY_ROLE.get(_MODULE_CATEGORY.get(module, ""))
        if role:
            counts[role] = counts.get(role, 0) + 1
    for requirement in requirements:
        for role in ROLE_ORDER:
            if role not in _NOT_TECH_DRIVEN and _keyword_weight(role, requirement) == _STRONG:
                counts[role] = counts.get(role, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], ROLE_ORDER.index(kv[0])))
    limit = max(2, team_size)
    return [{"role": role, "weight": n, "priority": i < limit} for i, (role, n) in enumerate(ordered)]


def team_coverage(fits: list[dict[str, Any]], needs: list[dict[str, Any]]) -> dict[str, Any]:
    """Team-level view over the individual fits: who covers what the project
    needs, where responsibilities overlap, and one complementary assignment.

    Advisory only - nothing here is stored or applied. `plan` may differ from a
    member's own best role (`differs`) precisely when that makes the team's
    coverage better; the member's individual suggestion is left untouched.
    """
    people = [f for f in fits if f["suggested"]]
    primary = {f["name"]: f["suggested"]["role"] for f in people}

    covered, gaps = [], []
    for need in needs:
        role = need["role"]
        owners = [n for n, r in primary.items() if r == role]
        could = [
            f["name"] for f in people
            if f["name"] not in owners and f["fits"][role]["score"] >= ALTERNATIVE_MIN_SCORE
        ]
        if owners:
            covered.append({"role": role, "priority": need["priority"], "primary": owners, "could_also_cover": could})
        elif need["priority"]:
            candidates = sorted(
                ((f["fits"][role]["score"], f["name"]) for f in people if f["fits"][role]["score"] >= MIN_SUGGEST_SCORE),
                key=lambda c: (-c[0], c[1]),
            )
            gaps.append({
                "role": role,
                "candidates": [{"member": n, "score": s} for s, n in candidates[:3]],
                "note": (
                    f"No one's best role is {role}, but {candidates[0][1]} could cover it alongside their main role."
                    if candidates else f"No one on the team lists skills that point to {role}."
                ),
            })

    # Complementary assignment: the best-scoring person for each priority role,
    # one role per person; everyone else keeps their own best role.
    pairs = sorted(
        (-f["fits"][n["role"]]["score"], ROLE_ORDER.index(n["role"]), f["name"], n["role"])
        for f in people for n in needs
        if n["priority"] and f["fits"][n["role"]]["score"] >= MIN_SUGGEST_SCORE
    )
    plan_role: dict[str, str] = {}
    taken: set[str] = set()
    for _score, _order, name, role in pairs:
        if name not in plan_role and role not in taken:
            plan_role[name] = role
            taken.add(role)
    for f in people:
        plan_role.setdefault(f["name"], primary[f["name"]])
    plan = [
        {
            "member": f["name"],
            "user_id": f["user_id"],
            "role": plan_role[f["name"]],
            "individual_role": primary[f["name"]],
            "differs": plan_role[f["name"]] != primary[f["name"]],
            "score": f["fits"][plan_role[f["name"]]]["score"],
        }
        for f in people
    ]

    # Overlap: several members with the same plan role. Reported plainly; called
    # out for rebalancing only when one of THOSE members is a candidate for a
    # role that has no owner - otherwise there is nowhere sensible to move to.
    by_role: dict[str, list[str]] = {}
    for item in plan:
        by_role.setdefault(item["role"], []).append(item["member"])
    overlaps = []
    for role, names in by_role.items():
        if len(names) < 2:
            continue
        movable = sorted(
            {(c["member"], g["role"]) for g in gaps for c in g["candidates"] if c["member"] in names}
        )
        note = f"{len(names)} people are all best matched to {role}."
        if movable:
            who, target = movable[0]
            note += f" {who} could take {target}, which has no owner yet."
        else:
            note += " That may be fine if the work is large enough to share."
        overlaps.append({"role": role, "members": names, "note": note, "rebalance": bool(movable)})

    multi = [
        {"member": f["name"], "roles": [r["role"] for r in [f["suggested"], *f["alternatives"]]]}
        for f in people if f["alternatives"]
    ]
    return {
        "needed_roles": needs,
        "covered": covered,
        "gaps": gaps,
        "overlaps": overlaps,
        "multi_role_members": multi,
        "plan": plan,
        "optional_roles": [n["role"] for n in needs if not n["priority"]],
    }


def role_fit(doc: Optional[dict[str, Any]], members: list[dict[str, Any]]) -> dict[str, Any]:
    """Individual suggestions plus team coverage for a roster.

    members: [{id, name, source: profile|profile+manual|manual|none,
    skills: [{name, level|None}], preferred_roles, interests, profile_status}].
    `doc` may be None or lack requirements: individual suggestions then rest on
    skills alone (no coverage component, no missing-skill list).
    """
    doc = doc or {}
    requirements = [
        s for s in [*doc.get("technologies", []), *doc.get("skills", [])] if isinstance(s, str) and s.strip()
    ]
    domain = doc.get("domain", "")
    fits = [member_role_fit(m, requirements, domain) for m in members]
    needs = needed_roles(doc, requirements, len(members)) if doc else []
    return {
        "score_meaning": SCORE_MEANING,
        "has_project_requirements": bool(requirements),
        "members": [{k: v for k, v in f.items() if k != "fits"} for f in fits],
        "team": team_coverage(fits, needs),
    }
