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
gated behind an optional API key (see [AI Assistant](#-ai-assistant)).

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
  (bounded to 15% of the score — see [`backend/README.md`](backend/README.md))
- Explainable results — cards show *why* a project matched, not just a score
- Résumé matcher — upload a PDF/DOCX and get ranked project suggestions
- Voice search (Web Speech API)

## Once you've picked a project

- Auto-generated synopsis and week-by-week roadmap, exportable to PDF
- Skill-gap analysis against a project's requirements, with a learning path
  (real tutorial/course links per missing skill)
- Team-role suggestions from a list of teammates' skills
- Timeline prediction (estimated completion time for a team size/experience level)
- "Is my idea original?" duplicate-detection check
- A shared team workspace: invite code, member list, message board
- Favourites and search history (device-scoped, no account needed)

## AI Assistant (optional — needs `GROQ_API_KEY`)

- **Ask about this project** — a chat widget on each project's page, grounded
  in that project's own fields, with Markdown replies, message copy, and a
  history that persists locally per project
- **Full assistant page** (`/chat`) — a ChatGPT-style page with a sidebar of
  saved conversations, for general brainstorming/debugging/concept questions
  not tied to one project

## Accounts & notifications

- Lightweight email/password accounts (bearer-token sessions, no third-party
  auth) — used only for teams and notifications; search, favourites and
  history stay anonymous and device-scoped regardless of sign-in state
- In-app notifications, optionally mirrored to email over SMTP

## Analytics

- Aggregate dashboard: trending domains, popular technologies, search volume

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
from it. See [`backend/README.md`](backend/README.md#how-retrieval-works)
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
- Groq (Llama 3.3 70B) — the one LLM-backed feature, optional

## Database

- MongoDB (local `mongod` for development, MongoDB Atlas for production)

## Deployment

- Frontend → Vercel
- Backend → Render

---

# 📂 Folder Structure

```text
NLP- Project Recommendation System/
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── landing/         LandingHero, LandingNav, LandingFooter, WireframeCubes
│       │   ├── ProjectChat.jsx  project-grounded AI chat widget
│       │   ├── MarkdownLite.jsx dependency-free Markdown renderer for chat replies
│       │   ├── ProjectPlanner.jsx, TeamBuilder.jsx, ProjectCard.jsx, ...
│       │   └── Feedback.jsx, PageHeader.jsx, ErrorBoundary.jsx
│       ├── pages/                Search, Browse, ResumeMatch, Chat, Teams, TeamRoom,
│       │                         ProjectDetail, Favorites, History, Analytics,
│       │                         Dashboard, Account, About
│       ├── hooks/                useAuth, useFavorites, useVoiceSearch
│       ├── services/api.js       axios client, device/auth identity, error normalising
│       └── utils/pdf.js
│
├── backend/
│   ├── app.py                   Flask application factory
│   ├── config.py                all environment-driven configuration
│   ├── routes/                  search, projects, user, assistant, auth, teams, notifications
│   ├── nlp/                     preprocess, embeddings, similarity, recommend, generator,
│   │                             skill/team/timeline/learning_path tools, ai_assistant, resume
│   ├── auth/                    email/password + bearer-token sessions
│   ├── teams/                   team workspace service layer
│   ├── db/                      MongoDB client, indexes, schema
│   ├── dataset/projects_seed.json   500 seed projects across 14 domains
│   ├── data/                    embeddings.npy + ids.json (built, not committed)
│   ├── scripts/                 seed_db, build_index, evaluate, validate_dataset, smoke_search
│   └── tests/                   76 tests (pytest)
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
[`backend/README.md`](backend/README.md#api) for details.

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/health` | Per-dependency status |
| POST | `/api/search` | Hybrid semantic + keyword search |
| GET | `/api/projects` | Paginated browse |
| GET | `/api/project/<id>` | Single project |
| GET | `/api/project/<id>/synopsis` | Generated synopsis |
| GET | `/api/project/<id>/roadmap` | Generated week-by-week roadmap |
| GET | `/api/similar/<id>` | Nearest projects by embedding |
| GET | `/api/filters` | Filter options for the UI |
| GET | `/api/analytics` | Aggregate counts + trending searches |
| POST | `/api/skill-gap` | Readiness % against a project |
| POST | `/api/team-builder` | Role suggestions from teammates' skills |
| POST | `/api/timeline-predict` | Estimated completion time |
| POST | `/api/learning-path` | Resources for a list of skills |
| POST | `/api/uniqueness` | Duplicate-idea check |
| POST | `/api/resume-suggest` | Résumé (PDF/DOCX or text) → ranked projects |
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
| POST / GET | `/api/teams`, `/api/teams/join`, `/api/teams/mine`, `/api/teams/<id>` | Team workspace |
| GET / POST | `/api/teams/<id>/messages` | Team message board |
| GET / POST | `/api/notifications`, `/api/notifications/<id>/read`, `/api/notifications/read-all` | In-app notifications |

---

# 📱 Frontend Pages

`Search` (index/landing) · `Browse` · `Résumé Match` · `Chat` · `Teams` /
`Team Room` · `Project Detail` · `Favourites` · `History` · `Analytics` ·
`Dashboard` (conversational project search) · `Account` · `About`

---

# 🎨 Design System

The whole app shares one visual identity — **"Gallery Mono"**, a strict dark
monochrome system (see [`DESIGN.md`](DESIGN.md) for the full token set).
There is no light-mode toggle; it's dark by design, not a default half of a
theme switch.

---

# 🤖 AI Assistant

The one LLM-backed part of the app, via [Groq](https://groq.com). Everything
else — search, skill-gap, uniqueness, roadmap generation, team building,
timeline prediction — is a deterministic function over the project's own
fields, on purpose: no external cost, no API key required, nothing to
hallucinate. Free-form Q&A genuinely needs open-ended generation, so it's the
one exception, and the rest of the app is fully functional with
`GROQ_API_KEY` unset.

- **Project chat** — stateless on the server; the frontend resends the
  conversation each turn, grounded in one project's title/domain/description/
  technologies/skills.
- **General chat** (`/chat`) — persists conversations server-side per device
  (no project in scope), with a saved-conversation sidebar.

Set `GROQ_API_KEY` in `backend/.env` to enable both.

---

# 🚀 Installation

## Clone

```bash
git clone <this-repository-url>
cd "NLP- Project Recommendation System"
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
CUDA-bundled default. See [`backend/README.md`](backend/README.md) for why.

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
server — see [`backend/README.md`](backend/README.md#running-in-production).

---

# 🧪 Testing

```powershell
cd backend
venv\Scripts\python -m pytest tests/ -v     # 76 tests

cd frontend
npm run lint                                 # oxlint
npm run build                                # production bundle + type-level checks
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
