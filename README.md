 # 🎓 ProjectMind AI

### AI-Powered NLP Project Recommendation System for Students

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Flask](https://img.shields.io/badge/Flask-Backend-black)
![React](https://img.shields.io/badge/React-19-61DAFB)
![NLP](https://img.shields.io/badge/NLP-SentenceTransformers-green)
![MongoDB](https://img.shields.io/badge/MongoDB-Database-green)
![Groq](https://img.shields.io/badge/Groq-LLM%20Assistant-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

# 📖 Overview

ProjectMind AI is a web application that helps students find a final-year or
semester project by describing what they want in plain English, instead of
keyword-searching a list. A hybrid retrieval engine (dense sentence
embeddings + BM25) ranks a catalogue of 500 project briefs by semantic
relevance, then the rest of the app helps a student go from "found a project"
to "know how to build it": readiness checks, a generated roadmap, team
formation, a résumé matcher, and an optional AI mentor to ask follow-up
questions.

Everything except the AI mentor chat is deterministic — no external API call,
no hallucination risk, nothing required to run the app. The chat is the one
place open-ended generation is genuinely needed, so it is the one feature
gated behind an optional API key (see "AI Assistant, RAG & Tool-Calling
Pipeline" below).

---

# 🎯 Problem Statement

Selecting a final-year or semester project is often difficult because students:

- Spend hours searching online
- Receive repetitive project ideas
- Cannot match projects with their skills
- Don't know which technologies to choose
- Lack proper learning resources
- Have difficulty finding innovative topics

Current search methods rely mainly on keywords and fail to understand the
actual intent behind user queries.

---

# 💡 Solution

ProjectMind AI understands student requirements expressed in plain English.

Example query:

> "I want an AI-based healthcare project using Python."

The system encodes the query as a sentence embedding, blends that with BM25
keyword scoring, ranks it against 500 project descriptions, and returns the
most relevant matches with technologies, difficulty, a duration estimate,
required skills, a reference repository, and learning resources.

---

# ✨ Features

## Discovery

- Natural-language semantic search (dense embeddings + BM25 hybrid)
- Domain, technology and difficulty filtering
- "Similar projects" via nearest-embedding lookup
- Personalised ranking from a device's own favourites/search history
  (bounded to 15% of the score — see [`backend/README_Backend.md`](backend/README_Backend.md))
- Explainable results — cards show *why* a project matched, not just a score
- Résumé matcher — upload a PDF/DOCX and get ranked project suggestions
- Voice search (Web Speech API)

## AI ideation

No catalogue project fits? Describe a domain/interest and the assistant
generates new project concepts — not by prompting the model once and
trusting the output, but a pipeline (`nlp/ideation.py`):

1. **Generate** — a structured, strict-JSON generation call (title,
   problem/solution, unique angle, tech stack, difficulty, duration).
2. **Validate** — parsed and field-checked against the app's real
   domain/difficulty enums.
3. **Check originality** — every idea is run back through the *same*
   `check_uniqueness()` the standalone Idea Check page uses (real embedding
   similarity against the catalogue) — not a second, separate heuristic.
4. **Auto-regenerate** — an idea scoring below the originality floor gets
   one targeted regeneration pass *before* it's ever shown, rather than
   being presented as though it were novel.
5. **Refine** — a follow-up like *"make it more innovative"* or *"use React
   instead"* regenerates one idea in place, re-validated the same way.

Once generated, an idea gets its own synopsis, roadmap, skill-gap check, and
can start a team directly — the exact same deterministic planning tools a
catalogue project uses, fed the idea's own fields instead of a Mongo lookup,
never a second implementation.

## Recommendation & evaluation

- "Best fit for you" — a dedicated panel (`/api/recommend`) that blends
  search relevance, skill-gap fit, and timeline fit into one explained,
  weighted score, distinct from plain keyword/semantic search
- "Is my idea original?" — duplicate-detection against the whole catalogue
  by meaning, with the closest matches and *why* they overlap, not just a
  score
- The assistant's own **decision engine** (`recommend_decision`, reachable
  via chat) scores several already-shown/compared projects on skill fit,
  timeline fit, difficulty fit, and uniqueness at once, for "which one
  should I actually pick?"

## Once you've picked a project

- Auto-generated synopsis and week-by-week roadmap, exportable to PDF
- Skill-gap analysis against a project's requirements, with a learning path
  (real tutorial/course links per missing skill)
- Team-role suggestions from a list of teammates' skills
- Timeline prediction (estimated completion time for a team size/experience level)
- Favourites and search history (device-scoped, no account needed)

## Teams

A shared workspace for building the project together, once one is selected —
`backend/teams/`, needs a signed-in account (the one feature that does):

- Create a team from a catalogue project *or* a generated idea; a
  6-character invite code (visible to the owner only) to invite teammates
- Rename (owner-only), leave, or have the owner remove a member
- Each member records their own skills; role suggestions are generated from
  the team's real roster against the project's actual modules — the same
  engine `/api/team-builder` uses standalone, not a second one
- A message board (polled, not WebSockets — see Known Limitations), with an
  in-app notification (optionally emailed) on joins and new messages

## AI Assistant (optional — needs `GROQ_API_KEY`)

- **Ask about this project** — a chat widget on each project's page, grounded
  in that project's own fields, with Markdown replies, message copy, and a
  history that persists locally per project
- **Dashboard** (`/dashboard`) — a ChatGPT-style conversational page fusing
  project search and general brainstorming/debugging/concept questions into
  one thread, with a sidebar of saved conversations

## Accounts & notifications

- Lightweight email/password accounts (bearer-token sessions, no third-party
  auth) — used only for teams and notifications; search, favourites and
  history stay anonymous and device-scoped regardless of sign-in state
- In-app notifications (mark one read or all at once), optionally mirrored to
  email over SMTP

---

# 🧠 NLP Workflow

```text
User Query
    │
    ▼
Two parallel preprocessing paths
    ├── clean_for_embedding()   → minimal cleaning, feeds the transformer
    └── tokens_for_bm25()        → tokenise, stopword-remove, lemmatise
    │
    ▼
Dense sentence embedding (all-MiniLM-L6-v2, 384-d)  +  BM25 keyword score
    │
    ▼
Weighted fusion (dense 0.80 / sparse 0.20 — measured, see config.py)
    │
    ▼
Filter by domain / difficulty / technology / duration
    │
    ▼
Optional personalisation blend (≤ 15% weight)
    │
    ▼
Ranked, explained results
```

Sentence-transformer models are trained on natural sentences and rely on word
order and function words for meaning, so the classic
tokenise-stopword-lemmatise pipeline is deliberately **not** applied before
embedding — only before BM25, which is bag-of-words and genuinely benefits
from it. See [`backend/README_Backend.md`](backend/README_Backend.md#how-retrieval-works)
for the full reasoning and measured numbers.

---

# 🏗️ System Architecture

```text
React 19 SPA (Vite, Tailwind v4, Framer Motion)
        │  axios, X-Device-Id / X-Auth-Token headers
        ▼
Flask REST API  (rate-limited on cost-bearing routes only)
        │
        ├── Hybrid retrieval  (nlp/embeddings, nlp/similarity, nlp/recommend)
        ├── Deterministic tools  (skill_gap, generator, team_builder,
        │                         timeline, learning_path, resume)
        ├── AI assistant  (nlp/ai_assistant.py → Groq, optional)
        └── Accounts / teams / notifications
        │
        ▼
MongoDB           +   data/embeddings.npy + data/ids.json
(projects, users,     (L2-normalised vectors, built offline by
 favourites, teams,    scripts/build_index.py — cosine similarity
 conversations, ...)   becomes a plain dot product)
```

---

# ⚙️ Tech Stack

## Frontend

- React 19 + Vite 8
- Tailwind CSS v4
- Framer Motion
- React Router v7
- Axios
- Three.js (landing page WebGL background)
- jsPDF (synopsis/roadmap export)

## Backend

- Python 3.11 + Flask
- Flask-CORS, Flask-Limiter
- PyMongo (MongoDB)
- Waitress (production WSGI server)

## NLP / ML

- Sentence-Transformers (`all-MiniLM-L6-v2`)
- NLTK, spaCy
- scikit-learn (BM25-style scoring, cosine similarity)
- Groq (`openai/gpt-oss-20b` chat, `openai/gpt-oss-120b` tool-calling) — the one LLM-backed feature, optional

## Database

- MongoDB (local `mongod` for development, MongoDB Atlas for production)

## Deployment

- Frontend → Vercel
- Backend → Render

---

# 📂 Folder Structure

```text
ProjectMindAi/
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── landing/         LandingHero, ShaderBackground, WireframeCubes
│       │   ├── ChatPrimitives.jsx  CopyButton, TypingDots (shared by Dashboard + ProjectChat)
│       │   ├── ProjectChat.jsx  project-grounded AI chat widget
│       │   ├── MarkdownLite.jsx dependency-free Markdown renderer for chat replies
│       │   ├── ProjectPlanner.jsx, TeamBuilder.jsx, ProjectCard.jsx, ...
│       │   ├── BlueprintCard.jsx, GeneratedIdeaCard.jsx  AI-generated idea cards (Ideate/Dashboard)
│       │   ├── SkillGapPanel.jsx, RecommendedForYou.jsx, StartTeamWorkspace.jsx
│       │   ├── Modal.jsx, AuthGateModal.jsx  focus-trapped dialogs (useFocusTrap.js)
│       │   └── Feedback.jsx, PageHeader.jsx, ErrorBoundary.jsx
│       ├── pages/                Search, Ideate, IdeaDetail, ResumeMatch, UniquenessCheck,
│       │                         Teams, TeamRoom, ProjectDetail, Favorites, History,
│       │                         Dashboard, Account
│       ├── hooks/                useAuth, useFavorites, useVoiceSearch
│       ├── services/api.js       axios client, device/auth identity, error normalising
│       ├── test/                 Vitest setup + renderWithProviders test helper
│       └── utils/pdf.js
│
├── backend/
│   ├── app.py                   Flask application factory
│   ├── config.py                all environment-driven configuration
│   ├── routes/                  search, projects, user, assistant, ideas, auth, teams, notifications
│   ├── nlp/                     preprocess, embeddings, similarity, recommend, generator,
│   │                             skill/team/timeline/learning_path tools, ai_assistant, resume
│   ├── auth/                    email/password + bearer-token sessions
│   ├── teams/                   team workspace service layer (project- or idea-backed)
│   ├── db/                      MongoDB client, indexes, schema
│   ├── dataset/projects_seed.json   500 seed projects across 14 domains
│   ├── data/                    embeddings.npy + ids.json (built, not committed)
│   ├── scripts/                 seed_db, build_index, evaluate, validate_dataset, smoke_search
│   └── tests/                   581 tests (pytest)
│
├── ROADMAP.md                   product roadmap / vision (source of truth for planning)
├── DESIGN.md                    "Gallery Mono" design tokens
└── README.md
```

---

# 🗂️ Dataset Structure

500 project briefs across 14 domains (AI, Computer Vision, NLP, Deep
Learning, Machine Learning, Data Science, Web Development, Mobile
Development, IoT, Robotics, Blockchain, Cybersecurity, Cloud & DevOps,
AR/VR). Each record:

| Field | Description |
|---|---|
| `project_id` | Unique ID |
| `title` | Project name |
| `description` | Short summary |
| `domain` | One of the 14 domains above |
| `technologies` | e.g. Python, React, YOLOv8 |
| `difficulty` | Beginner / Intermediate / Advanced |
| `duration_weeks` | Estimated completion time |
| `skills` | Skills required |
| `keywords` | Search tags (feeds the sparse/BM25 side) |
| `github_url` | A *reference* repo for the core technology — these are briefs, not built projects, so this points at the upstream tool (e.g. YOLOv8 → `ultralytics`), labelled "Reference repo" in the UI |
| `learning_resources` | Tutorial links |

---

# 🌐 API Endpoints

All responses are wrapped: `{"data": ...}` on success, `{"error": "..."}` on
failure. Routes needing identity read `X-Device-Id` (anonymous, always) or
`X-Auth-Token` (signed-in, teams/notifications only) — see
[`backend/README_Backend.md`](backend/README_Backend.md#api) for details.

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/health` | Per-dependency status — Mongo, search index (incl. staleness vs. the catalogue), AI model reachability |
| POST | `/api/search` | Hybrid semantic + keyword search |
| GET | `/api/projects` | Paginated browse |
| GET | `/api/project/<id>` | Single project |
| GET | `/api/project/<id>/synopsis` | Generated synopsis |
| GET | `/api/project/<id>/roadmap` | Generated week-by-week roadmap |
| GET | `/api/project/<id>/milestones` | Build checkpoints derived from the roadmap |
| GET | `/api/similar/<id>` | Nearest projects by embedding |
| GET | `/api/filters` | Filter options for the UI |
| POST | `/api/skill-gap` | Readiness % against a project |
| POST | `/api/team-builder` | Role suggestions from teammates' skills |
| POST | `/api/timeline-predict` | Estimated completion time |
| POST | `/api/learning-path` | Resources for a list of skills |
| POST | `/api/uniqueness` | Duplicate-idea check |
| POST | `/api/resume-suggest` | Résumé (PDF/DOCX or text) → ranked projects |
| POST | `/api/recommend` | Explainable multi-factor "best fit for you" ranking |
| POST | `/api/idea/{skill-gap,synopsis,roadmap,milestones,timeline,team-builder,chat}` | Same tools as above, for a not-yet-catalogued AI-generated idea |
| POST / DELETE | `/api/favorite`, `/api/favorite/<id>` | Save / remove |
| GET | `/api/favorites` | Full project documents |
| GET / DELETE | `/api/history` | Recent searches |
| POST | `/api/feedback` | Rating and/or free-text feedback |
| POST | `/api/project/<id>/chat` | Project-grounded AI chat (stateless, rate-limited) |
| GET / POST | `/api/conversations` | List / start a general AI chat conversation |
| GET / DELETE | `/api/conversations/<id>` | Read / delete a conversation |
| POST | `/api/conversations/<id>/messages` | Send a message, get a reply (rate-limited) |
| POST | `/api/auth/signup`, `/api/auth/login`, `/api/auth/logout` | Account auth |
| GET | `/api/auth/me` | Current session |
| POST / GET | `/api/teams`, `/api/teams/join`, `/api/teams/mine`, `/api/teams/<id>` | Team workspace — create from a `project_id` or a generated `idea` |
| PATCH | `/api/teams/<id>` | Rename (owner-only) |
| DELETE | `/api/teams/<id>/members/<uid>` | Leave, or owner removes a member |
| POST | `/api/teams/<id>/skills` | Record your own skills for role-matching |
| GET | `/api/teams/<id>/roles` | Role suggestions for the team's real roster |
| GET / POST | `/api/teams/<id>/messages` | Team message board |
| GET / POST | `/api/notifications`, `/api/notifications/<id>/read`, `/api/notifications/read-all` | In-app notifications |

---

# 📱 Frontend Pages

`Search` (index/landing) · `Ideate` (AI idea generation) · `Idea Detail` ·
`Résumé Match` · `Idea Check` (uniqueness) · `Teams` / `Team Room` ·
`Project Detail` · `Favourites` · `History` · `Dashboard` (conversational
project search) · `Account`

---

# 🎨 Design System

The whole app shares one visual identity — **"Gallery Mono"**, a strict dark
monochrome system (see [`DESIGN.md`](DESIGN.md) for the full token set).
There is no light-mode toggle; it's dark by design, not a default half of a
theme switch.

---

# 🤖 AI Assistant, RAG & Tool-Calling Pipeline

The one LLM-backed part of the app, via [Groq](https://groq.com). Everything
else — search, skill-gap, uniqueness, roadmap generation, team building,
timeline prediction — is a deterministic function over the project's own
fields, on purpose: no external cost, no API key required, nothing to
hallucinate. Free-form Q&A and open-ended idea generation genuinely need an
LLM, so they're the one exception, and the rest of the app is fully
functional with `GROQ_API_KEY` unset. Two Groq models are used, for two
different reliability requirements (see `backend/config.py`'s own comments
for the measured reasoning): `GROQ_MODEL` (`openai/gpt-oss-20b` by default)
for plain grounded replies and idea generation, and `GROQ_TOOL_MODEL`
(`openai/gpt-oss-120b`) specifically for tool-calling, which needs a model
that reliably emits native tool calls rather than a text-based imitation of
one.

## AI Mentor (project-grounded chat)

The **"Ask about this project"** widget on a project's own page —
`nlp/ai_assistant.py:reply()`. Stateless on the server (the frontend resends
the running conversation each turn), and grounded directly in that one
project's real title/domain/description/technologies/skills, injected into
its system prompt before the first token is generated. It's explicitly a
*mentor*, not an implementer: the prompt instructs it to give guidance and
plans, never to claim it has written, tested, or changed the student's
actual code, and to say plainly when something isn't specified in the
project's own data rather than inventing an answer. No tools are attached
here — it already has everything it needs in its own system message, so
there's nothing to retrieve.

## Dashboard assistant (RAG + tool-calling)

The general, no-fixed-project chat at `/dashboard` —
`nlp/ai_assistant.py:general_reply()`. This is genuinely RAG-grounded, not a
free-generation chatbot: it calls out to a fixed set of ~20 tools
(`nlp/chat_tools.py`), each one a thin wrapper over an *existing*
deterministic function (hybrid search, a Mongo lookup, the roadmap
generator, skill-gap, timeline prediction, team-building, uniqueness
checking, ...) — never a second implementation of any of them. Every fact
the model states about a project or a plan traces back to one of these real
tool results; it never invents a project, technology, or score.

- **DISCOVERY vs IDEATION routing** — the system prompt explicitly
  distinguishes "find something that already exists" (→ `search_projects`)
  from "invent something new" (→ `generate_project_ideas`), the single most
  important routing decision the assistant makes.
- **Context notes** — earlier turns that showed projects or generated ideas
  carry a compact, model-facing note (id/title/fields, in order) so a
  follow-up like *"the second one"*, *"make it easier"*, or *"create a
  roadmap for that"* resolves correctly without a bespoke reference
  resolver. A student's currently-selected project/idea and any
  already-uploaded résumé skills are threaded the same way.
- **Reliability engineering** — multi-API-key rotation on rate limits,
  bounded retry with backoff on transient failures, and a graduated
  history-shrinking retry when a request is rejected as too large for the
  account's token budget. `/api/health`'s `ai_assistant.model_status` adds a
  cached (5 min), zero-completion-token reachability check for the
  configured model(s) — the one thing none of the above would ever notice
  on its own if Groq deprecated or renamed the configured model.

Set `GROQ_API_KEY` in `backend/.env` to enable both.

---

# 🚀 Installation

## Clone

```bash
git clone https://github.com/Tirthvaghela/ProjectMindAi.git
cd ProjectMindAi
```

## Backend

Prerequisites: Python 3.11, MongoDB running on `localhost:27017`.

```powershell
cd backend
python -m venv venv
venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

Installing the CPU-only PyTorch wheel first avoids pulling the ~2.5 GB
CUDA-bundled default. See [`backend/README_Backend.md`](backend/README_Backend.md) for why.

```powershell
venv\Scripts\python -m scripts.seed_db        # load the 500 seed projects into MongoDB
venv\Scripts\python -m scripts.build_index    # compute embeddings (downloads the model, ~90 MB)
venv\Scripts\python app.py                    # serve on http://127.0.0.1:5000
```

Optional: set `GROQ_API_KEY` in `backend/.env` to enable the AI assistant.

## Frontend

```powershell
cd frontend
npm install
npm run dev      # http://localhost:5173
```

---

# 🔑 Environment Variables

All backend configuration is environment-driven (`backend/config.py`) —
`copy .env.example .env` above already has every variable below with a safe
default or an empty placeholder. Nothing here is required except MongoDB
itself; everything AI-related is optional and the app runs fully without it.

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_URI`, `MONGO_DB` | `mongodb://localhost:27017`, `projectmind` | Database connection — only line that changes to move to Atlas |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `sentence-transformers/all-MiniLM-L6-v2`, `384` | The sentence-transformer used to build/query the search index |
| `DENSE_WEIGHT`, `SPARSE_WEIGHT` | `0.80`, `0.20` | Hybrid search fusion weights — measured optimum, change both together |
| `DEFAULT_TOP_K`, `MAX_TOP_K` | `10`, `50` | Result-count bounds |
| `DUPLICATE_THRESHOLD` | `0.92` | Similarity above which two projects are flagged as near-duplicates |
| `PERSONALIZATION_WEIGHT`, `PERSONALIZATION_QUERY_WEIGHT`, `PERSONALIZATION_MAX_QUERIES` | `0.15`, `0.4`, `5` | How much a device's own favourites/history can shift ranking; `0` disables it |
| `FLASK_HOST`, `FLASK_PORT` | `127.0.0.1`, `5000` | Where the dev server binds |
| `FLASK_DEBUG` | `0` | **Leave at `0` anywhere this might be deployed** — `1` enables Werkzeug's interactive debugger, which can execute arbitrary code from the browser on an unhandled exception |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowlist, not a wildcard |
| `MAX_HISTORY_PER_DEVICE` | `50` | Per-device search-history cap |
| `GROQ_API_KEY` | *(empty)* | Enables the AI assistant + ideation entirely. Free key at [console.groq.com/keys](https://console.groq.com/keys); leave blank and every other feature still works |
| `GROQ_API_KEYS` | *(empty)* | Optional extra comma-separated keys to rotate across on a rate limit |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Plain chat/ideation model |
| `GROQ_TOOL_MODEL` | `openai/gpt-oss-120b` | Tool-calling model for the Dashboard assistant — deliberately a different, larger model; see the AI section above |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | *(empty)* | Optional email mirror for in-app notifications, which work regardless |

Frontend: `VITE_API_BASE_URL` (build-time only) overrides the default `/api`
base path — only needed when the frontend and backend are deployed on
different origins.

---

# ▶️ Running the Project

```powershell
# backend
cd backend
venv\Scripts\python app.py

# frontend (separate terminal)
cd frontend
npm run dev
```

Open `http://localhost:5173`. Check the backend independently with
`curl http://127.0.0.1:5000/api/health`.

For production, serve the backend through Waitress rather than Flask's dev
server — see [`backend/README_Backend.md`](backend/README_Backend.md#running-in-production).

---

# 🧪 Testing

```powershell
cd backend
venv\Scripts\python -m pytest tests/ -v     # 581 tests

cd frontend
npm run lint                                 # oxlint
npm run build                                # production bundle
npm run test                                 # 37 tests (Vitest + React Testing Library)
```

---

# 🧪 Sample Queries

```text
AI healthcare project
Computer Vision project using Python
Cybersecurity final year project
Machine Learning for agriculture
React Flask project
IoT smart home project
Blockchain voting system
Beginner NLP project
Deep Learning image classification
Smart attendance system
```

---

# 📸 Screenshots

> *(Add screenshots here.)*

---

# ⚠️ Known Limitations

Real, accepted trade-offs in what's already built — distinct from the
features below that simply don't exist yet.

- **Anonymous identity (`X-Device-Id`) is client-supplied and unverified.**
  Favourites, history, and anonymous chat are keyed on a UUID the browser
  generates and sends itself, with no server-side signing or binding to a
  session. Anyone who obtains another visitor's device id gets read/write
  access to that device's favourites/history/anonymous conversations. This
  is a deliberate trade-off for a frictionless, account-free experience on
  low-sensitivity data (see `routes/helpers.py:device_id`) — evaluated and
  accepted for the current student/demo scope rather than hardened, since
  doing so would mean redesigning the anonymous-identity model itself. Real
  accounts (signed-in, opaque session tokens) are unaffected and don't share
  this trade-off.
- **A handful of small UI components are still duplicated** across pages
  (the microphone button, the uniqueness-result/skill-gap-checklist/
  comparison-table displays, and `AuthGateModal` re-implementing parts of
  `Modal`/`Account`'s own form) rather than extracted into one shared
  component each. `CopyButton`/`TypingDots` (previously duplicated between
  Dashboard and ProjectChat) were consolidated into
  `components/ChatPrimitives.jsx`; the rest are identified but not yet
  extracted — see the technical audit for the full list.
- **The embedding index has no automatic rebuild.** `/api/health` reports
  `search_index.stale: true` when MongoDB and the on-disk index disagree
  (e.g. a project added without re-running `build_index`), but nothing
  rebuilds it automatically — that stays an explicit, operator-run step by
  design (see [`backend/README_Backend.md`](backend/README_Backend.md)).

---

# 🗺️ Roadmap

Day-to-day planning and in-progress work live in [`ROADMAP.md`](ROADMAP.md),
not here — check it before scoping new features so this file doesn't drift
out of sync with it again.

## Genuinely not built yet

- AI interview-prep mode
- Real GitHub-repository analysis (today `github_url` is a static reference
  link, not an analyzed repo)
- True real-time team chat (today's team message board polls every 4s)
- Multi-language UI (English only)
- A native mobile app

---

# 🎓 Learning Outcomes

Building this project touches:

- Natural language processing (preprocessing, tokenisation, lemmatisation)
- Sentence embeddings and semantic search
- Hybrid dense + sparse (BM25) retrieval and score fusion
- Recommendation systems and bounded personalisation
- Flask REST API design, rate limiting, and MongoDB integration
- React frontend architecture, routing, and state management
- Full-stack integration of an optional LLM feature behind a feature flag

---

# 👨‍💻 Authors

**Project:** ProjectMind AI — an academic NLP project built with React, Flask,
and Sentence-Transformers.

---

# 📜 License

Licensed under the **MIT License**. Free to use, modify, and distribute for
educational purposes.

---

## ⭐ If you like this project, don't forget to give it a star on GitHub!
#
