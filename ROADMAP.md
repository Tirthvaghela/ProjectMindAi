# 🎓 ProjectMind AI

## AI-Powered NLP Project Recommendation System for Students

> **Implementation status note (added after reading the actual codebase, 2026-08-11):**
> Section 19's "Current vs Future" table below undercounts what's already built. Items marked
> ❌ Future are already live in `backend/` and `frontend/`:
> - **Skill Gap Analysis** — `POST /api/skill-gap` (`nlp/recommend.py: skill_gap()`) + the "Am I ready
>   for this?" panel on the project detail page.
> - **Project Uniqueness Checker** — `POST /api/uniqueness` (`nlp/recommend.py: check_uniqueness()`)
>   + the "Is my project idea original?" panel on the About page.
> - **Analytics** — `GET /api/analytics` + the `/analytics` page (by-domain, by-difficulty,
>   top technologies, trending searches).
> - **One-Click Synopsis Generator + AI Project Roadmap Generator** (§5.1, §9) — added 2026-08-11.
>   Template-based, not LLM-backed (see `backend/nlp/generator.py` for why): `GET
>   /api/project/<id>/synopsis` and `GET /api/project/<id>/roadmap`, surfaced as the "Plan this
>   project" panel (`frontend/src/components/ProjectPlanner.jsx`) on the project detail page.
> - **Voice Search** (§10) — added 2026-08-11. Frontend-only, via the browser's built-in
>   `SpeechRecognition` API (`frontend/src/hooks/useVoiceSearch.js`), wired into the mic button on
>   the main search bar. No backend change, no new dependency — the button hides itself in browsers
>   that don't support the API (Firefox, notably).
> - **Team Builder** (§8) — added 2026-08-11. `POST /api/team-builder`
>   (`backend/nlp/team_builder.py`) assigns each teammate the project role (module) they're the
>   strongest fit for, reusing the same domain → modules breakdown the synopsis/roadmap generator
>   already computes. Surfaced as a "Team builder" panel on the project detail page.
> - **Personalized Learning Path** (§6) — added 2026-08-11. `POST /api/learning-path`
>   (`backend/nlp/learning_path.py`) turns a list of skills — typically the `skills_to_learn` the
>   skill-gap check already returns — into stable search links (YouTube, freeCodeCamp, Coursera,
>   plus official docs where the skill matches a known technology). No content API, so nothing is
>   a fabricated specific video/article. Surfaced as "Show me where to learn these" under the
>   skill-gap panel on the project detail page.
> - **Project Timeline Prediction** (§6) — added 2026-08-11. `POST /api/timeline-predict`
>   (`backend/nlp/timeline.py`) adjusts a project's baseline `duration_weeks` for team size and the
>   student's experience level relative to the project's own difficulty, via two named, explainable
>   multipliers (not a trained model — there's no historical completion-time data to train one on).
>   Reuses `nlp/generator.py`'s phase planner to re-plan phases against the personalised total.
>   Surfaced as "Personalize estimate" controls inside the Roadmap tab of "Plan this project".
> - **PDF Report Generator** (§9) — added 2026-08-11. Client-side, not server-side: the synopsis and
>   roadmap are already generated JSON by the time a student wants a copy, so `frontend/src/utils/pdf.js`
>   (jsPDF) renders straight from that in the browser rather than adding a PDF library to the backend.
>   "Download PDF" buttons on both tabs of "Plan this project".
> - **AI Chat Assistant / AI Project Mentor** (§5.1) — added 2026-08-11, merged into one feature
>   since they're the same capability (grounded Q&A about a project) under two names in this doc.
>   The one LLM-backed feature in this codebase — everything else here is deterministic on purpose
>   (see `backend/nlp/ai_assistant.py`). `POST /api/project/<id>/chat`, backed by Groq
>   (`llama-3.3-70b-versatile` by default), gated behind an optional `GROQ_API_KEY` in
>   `backend/.env` — every other feature in this app works with it unset. Rate-limited (20/hour)
>   since, unlike every other endpoint, each call has a real external cost. Surfaced as "Ask about
>   this project" on the project detail page, which only renders when `/api/health` reports the
>   assistant enabled. AI Interview Prep was considered and deliberately dropped — Chat Assistant
>   already covers "quiz me on this project" without a separate feature.
> - **Resume-Based Project Suggestions** (§6) — added 2026-08-11. `POST /api/resume-suggest`
>   (`backend/nlp/resume.py`) extracts text from an uploaded PDF/DOCX/TXT résumé (or pasted text),
>   detects skills by matching against the dataset's own technology/skill vocabulary, and feeds the
>   detected skills as a query straight into the existing hybrid search — no résumé-parsing API, no
>   second ranking algorithm. Nothing is stored; the file is read once per request and discarded.
>   New page: "Résumé Match".
> - **Lightweight accounts, Team Collaboration, Email Notifications** (§8, §9) — added 2026-08-11.
>   The first accounts this app has ever had — email/password, bearer-token sessions via a new
>   `X-Auth-Token` header (`backend/auth/service.py`), the same shape as the existing anonymous
>   `X-Device-Id` rather than cookies or a JWT library. **Scoped narrowly on purpose**: accounts
>   exist only for teams and notifications — favourites, history, search and personalisation all
>   still run purely off the device id, completely unchanged.
>   - **Teams** (`backend/teams/service.py`): create a team for a project, get a 6-character invite
>     code, teammates join with it. The "chat" is an async shared message board polled every 4s, not
>     real-time WebSockets — a handful of people posting occasionally doesn't justify a second
>     server process or a different production deployment story. New pages: "Teams" (list/join),
>     a per-team room (members + board), and a "Team workspace" panel on the project page. This is
>     separate from the pre-existing "Team builder" skill-matching panel, which stays stateless and
>     account-free.
>   - **Notifications** (`backend/notify.py`): always delivered in-app (bell icon, polled every
>     30s) regardless of configuration — the same "core feature needs zero setup, integration is
>     optional" trade-off as the AI assistant. Also emailed if `SMTP_HOST`/`SMTP_USER`/
>     `SMTP_PASSWORD` are set in `backend/.env`; left blank, email notifications simply don't fire
>     and nothing else is affected. Task assignment, file sharing and true real-time delivery were
>     explicitly left out of this pass.
>
> Treat this file as the target vision; check the current codebase before starting work on any item
> below in case it has since moved from Future to Current.

---

# 1. 📖 Project Overview

**ProjectMind AI** is an AI-powered student project recommendation platform that helps students find suitable academic project ideas using **Natural Language Processing (NLP)**.

Instead of searching manually through hundreds of project websites, students can simply describe what kind of project they want in natural language.

### Example

> "I want a healthcare project using Python and machine learning for my final year."

ProjectMind AI understands the meaning of the query using NLP and semantic similarity techniques and recommends the most relevant project ideas.

The system provides:

* Project recommendations
* Technology stack
* Difficulty level
* Required skills
* Estimated duration
* Learning resources
* GitHub repositories
* Similar projects

---

# 2. 🎯 Problem Statement

Students often struggle while selecting academic projects because:

* They don't know what project to choose.
* They spend a lot of time searching online.
* They find repeated or common project ideas.
* They don't know which technology is suitable.
* They cannot easily match projects with their skills.
* They don't know the difficulty or estimated completion time.
* They have difficulty finding proper learning resources.
* They want innovative and unique project ideas.

Traditional search engines mainly depend on keywords.

ProjectMind AI solves this problem by understanding the **semantic meaning and intent** of the student's query.

---

# 3. 💡 Proposed Solution

The student enters a project requirement in natural language.

For example:

> "Suggest me an intermediate AI project related to healthcare using Python."

The system processes the query using NLP and identifies relevant information such as:

* Domain → Healthcare
* Technology → Python
* Category → AI / Machine Learning
* Difficulty → Intermediate

The NLP engine then generates a sentence embedding and compares it with the embeddings of projects stored in the dataset.

The system calculates similarity scores and ranks the most relevant projects.

Finally, the student receives a list of recommended projects.

---

# 4. ✨ Current Features

## 4.1 🤖 AI Recommendation

* AI-powered project recommendation
* NLP-based semantic search
* Natural language project search
* Sentence Transformer embeddings
* Intelligent recommendation ranking
* Similar project suggestions
* Query understanding
* Cosine similarity-based matching

---

## 4.2 🔍 Smart Filtering

Students can narrow recommendations using:

* Domain
* Technology stack
* Difficulty level
* Estimated project duration

Example:

```text
Domain: Artificial Intelligence
Technology: Python
Difficulty: Intermediate
Duration: 3–4 Months
```

---

## 4.3 📋 Project Information

Each project contains detailed information such as:

* Project title
* Project description
* Required skills
* Technology stack
* Difficulty level
* Estimated duration
* Learning resources
* GitHub repository links
* Keywords
* Domain

---

## 4.4 👤 User Features

Students can:

* Search using plain English
* Get personalized recommendations
* Save favorite projects
* View search history
* View recent searches
* Explore learning resources
* Access GitHub repositories

---

## 4.5 🧠 NLP Engine

The NLP engine performs:

```text
User Query
     ↓
Text Preprocessing
     ↓
Tokenization
     ↓
Stopword Removal
     ↓
Lemmatization
     ↓
Sentence Embedding
     ↓
Semantic Similarity
     ↓
Recommendation Ranking
```

Technologies:

* NLTK
* spaCy
* Sentence Transformers
* scikit-learn

---

## 4.6 🎨 User Interface

The frontend provides:

* Responsive design
* Modern UI
* Dark mode
* Light mode
* Recommendation cards
* Search interface
* Filter interface
* Project details page
* Smooth navigation

---

## 4.7 ⚙️ Backend & API

The Flask backend provides REST APIs for:

* Project search
* Project details
* Similar projects
* Favorites
* Search history
* User feedback

### Main APIs

| Method | Endpoint           | Purpose                       |
| ------ | ------------------ | ----------------------------- |
| POST   | `/api/search`      | Search and recommend projects |
| GET    | `/api/projects`    | Get projects                  |
| GET    | `/api/project/:id` | Get project details           |
| GET    | `/api/similar/:id` | Find similar projects         |
| POST   | `/api/favorite`    | Save favorite                 |
| GET    | `/api/history`     | Get search history             |
| POST   | `/api/feedback`    | Submit feedback               |

---

# 5. 🚀 Future Features

The future version of ProjectMind AI can be expanded into a complete **AI Project Planning Assistant**.

---

## 5.1 🤖 AI Features

### AI Project Roadmap Generator

After selecting a project, AI generates a complete development roadmap.

Example:

```text
Project Selected
      ↓
Requirement Analysis
      ↓
Database Design
      ↓
Backend Development
      ↓
Frontend Development
      ↓
AI/NLP Integration
      ↓
Testing
      ↓
Deployment
```

---

### 💬 AI Chat Assistant

Students can ask questions about their selected project.

Example:

> "Which database should I use?"

> "How can I implement the recommendation engine?"

> "Explain this project's architecture."

---

### 📄 One-Click Project Synopsis Generator

Generate:

* Abstract
* Problem Statement
* Objectives
* Scope
* Methodology
* Modules
* Technology Stack
* Expected Results
* Future Scope

---

### 🧑‍🏫 AI Project Mentor

The AI mentor can guide students throughout development and answer technical questions.

---

### 🧑‍💻 AI Interview Preparation

Generate interview questions based on the student's selected project and technology stack.

---

# 6. 🧠 Smart Recommendation Features

## 🎯 Skill Gap Analysis

Compare the student's current skills with the required skills for a project.

Example:

```text
Your Skills:
Python ✓
React ✓
MongoDB ✓

Required:
Python ✓
React ✓
MongoDB ✓
NLP ✗
Machine Learning ✗
```

The system then recommends what the student should learn.

---

## 📚 Personalized Learning Path

Based on missing skills, the system recommends:

* Courses
* Tutorials
* YouTube videos
* Documentation
* Books
* Practice resources

---

## 🔍 Explainable Recommendations

Instead of simply saying:

> "95% Match"

the system explains:

```text
Why this project?

✓ Python matched
✓ Healthcare matched
✓ Machine Learning matched
✓ Intermediate difficulty matched
✓ 3–4 month duration matched
```

---

## 📅 Project Timeline Prediction

Predict estimated project completion time based on:

* Project complexity
* Team size
* Student experience
* Required technologies
* Number of modules

---

## 📄 Resume-Based Project Suggestions

Students can upload their resume.

The system analyzes their skills and recommends projects that match their existing experience.

---

# 7. 📊 Analytics Features

Future analytics dashboard can display:

### Trending Domains

```text
AI / ML             40%
Web Development     25%
Cybersecurity       15%
IoT                 12%
Blockchain           8%
```

### Popular Technologies

* Python
* React
* Flask
* Machine Learning
* MongoDB
* TensorFlow

### User Analytics

* Total searches
* Most searched topics
* Most viewed projects
* Most saved projects
* Popular technologies
* Popular domains

### Recommendation Accuracy

Track user feedback to improve the recommendation system.

---

# 8. 👥 Collaboration Features

## Team Builder

Students enter:

```text
Team Size: 4

Skills:
Python
React
UI/UX
Database
```

The system recommends suitable project roles.

Example:

```text
Member 1 → AI / Backend
Member 2 → Frontend
Member 3 → Database
Member 4 → UI/UX + Testing
```

---

## Team Collaboration

Future functionality can include:

* Shared projects
* Team workspace
* Task assignment
* Project progress
* Team chat
* File sharing

---

## 💬 Real-Time Chat

Allow project team members to communicate directly inside the application.

---

# 9. 📑 Productivity Features

## PDF Report Generator

Generate downloadable project documents.

Possible outputs:

* Project synopsis
* Project proposal
* Project roadmap
* Technology documentation
* Project report

---

## 🏆 Project Uniqueness Checker

Students can enter their own project idea.

The system compares it against existing projects and determines how similar it is.

Example:

```text
Your Project:
AI-Based Student Attendance System

Similarity with existing projects:

Project A → 87%
Project B → 72%
Project C → 45%

⚠️ Your idea may be too similar.
```

---

## 🔎 GitHub Repository Analyzer

Analyze recommended GitHub repositories and provide:

* Technologies used
* Repository structure
* Project complexity
* Activity
* Important modules
* Similar repositories

---

## 📧 Email Notifications

Future notifications can include:

* New project ideas
* Saved project updates
* Team notifications
* Recommendation updates

---

# 10. 🌍 Accessibility Features

## 🎤 Voice Search

Students can speak their requirements instead of typing.

Example:

> "Give me a machine learning project for healthcare."

Speech → Text → NLP → Recommendations

---

## 🌐 Multi-Language Support

Support:

* English
* Hindi
* Gujarati

This makes the platform more accessible to students who are not comfortable searching in English.

---

## 📱 Mobile Application

A future mobile application can provide the same functionality on Android and iOS.

---

# 11. 👤 Complete User Interaction Workflow

This is the main workflow of how a student interacts with ProjectMind AI.

```text
                    ┌──────────────────┐
                    │   Open Website   │
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │   Home Page      │
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │ Enter Requirement│
                    │  in Natural Lang.│
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │ Apply Filters    │
                    │ Domain/Tech/etc. │
                    └────────┬─────────┘
                             ↓
                    ┌──────────────────┐
                    │   AI Search      │
                    └────────┬─────────┘
                             ↓
                 ┌──────────────────────────┐
                 │      Flask Backend       │
                 └────────────┬─────────────┘
                              ↓
                 ┌──────────────────────────┐
                 │    NLP Processing        │
                 │                          │
                 │ • Preprocessing          │
                 │ • Tokenization           │
                 │ • Stopword Removal       │
                 │ • Lemmatization          │
                 │ • Sentence Embedding     │
                 └────────────┬─────────────┘
                              ↓
                 ┌──────────────────────────┐
                 │ Similarity Calculation   │
                 │   Cosine Similarity      │
                 └────────────┬─────────────┘
                              ↓
                 ┌──────────────────────────┐
                 │ Recommendation Engine    │
                 │      Ranking             │
                 └────────────┬─────────────┘
                              ↓
                 ┌──────────────────────────┐
                 │ Recommended Projects     │
                 └────────────┬─────────────┘
                              ↓
             ┌────────────────┴─────────────────┐
             ↓                                  ↓
    ┌─────────────────┐               ┌─────────────────┐
    │ View Details    │               │ Save Favorite   │
    └────────┬────────┘               └─────────────────┘
             ↓
    ┌─────────────────┐
    │ Explore Project │
    └────────┬────────┘
             ↓
    ┌─────────────────┐
    │ GitHub + Skills │
    │ + Resources     │
    └────────┬────────┘
             ↓
    ┌────────────────────────┐
    │ Select Final Project   │
    └────────────┬───────────┘
                 ↓
       ┌─────────────────────┐
       │ Future AI Features  │
       │                     │
       │ Roadmap             │
       │ Synopsis            │
       │ Skill Gap           │
       │ Learning Path       │
       │ Report Generation   │
       └─────────────────────┘
```

---

# 12. 🖥️ Frontend User Journey

## Step 1 — Landing Page

Student opens ProjectMind AI.

They see:

* ProjectMind AI introduction
* Search box
* Popular domains
* Trending technologies
* How it works
* Features

---

## Step 2 — Search

Student enters:

> "I need an NLP project using Python for my final year."

The student can optionally apply filters:

```text
Domain: NLP
Technology: Python
Difficulty: Intermediate
Duration: 3–4 Months
```

---

## Step 3 — AI Processing

The frontend sends the query to the Flask backend.

The backend processes it using the NLP pipeline.

```text
Query
 ↓
Preprocessing
 ↓
Embedding
 ↓
Similarity
 ↓
Ranking
```

---

## Step 4 — Recommendations

The student receives project cards.

Example:

```text
┌─────────────────────────────────┐
│ AI Healthcare Chatbot           │
│                                 │
│ NLP • Python • Flask            │
│                                 │
│ ⭐ 94% Match                    │
│                                 │
│ Intermediate                    │
│ 3–4 Months                      │
│                                 │
│ [View Details]  [♡ Save]        │
└─────────────────────────────────┘
```

---

# 13. 📋 Project Details Workflow

When the student clicks **View Details**:

```text
Project Details
      ↓
Overview
      ↓
Problem Statement
      ↓
Objectives
      ↓
Required Skills
      ↓
Technology Stack
      ↓
Architecture
      ↓
Modules
      ↓
GitHub Repository
      ↓
Learning Resources
      ↓
Similar Projects
```

---

# 14. ❤️ Favorite Workflow

```text
Recommendation
      ↓
Click ❤️
      ↓
Project Saved
      ↓
Favorites Page
      ↓
Compare Saved Projects
      ↓
Select Final Project
```

---

# 15. 🔎 Search History Workflow

Every search can be stored.

```text
Search Query
      ↓
Recommendation
      ↓
Search Saved
      ↓
History Page
      ↓
Click Previous Search
      ↓
Run Search Again
```

---

# 16. 🚀 Future AI Workflow

After selecting a project:

```text
Selected Project
       ↓
AI Project Mentor
       ↓
Skill Gap Analysis
       ↓
Learning Path
       ↓
Project Roadmap
       ↓
Synopsis Generation
       ↓
Development
       ↓
Testing
       ↓
Project Report
       ↓
Interview Preparation
```

This turns ProjectMind AI from a simple **project recommendation system** into a complete **AI-powered project planning and development assistant**.

---

# 17. 🏗️ Overall System Workflow

```text
┌─────────────────────┐
│       Student       │
└──────────┬──────────┘
           │
           │ Natural Language Query
           ↓
┌─────────────────────┐
│    React Frontend   │
└──────────┬──────────┘
           │
           │ REST API
           ↓
┌─────────────────────┐
│     Flask Backend   │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│    NLP Pipeline     │
│                     │
│ Preprocessing       │
│ Tokenization        │
│ Lemmatization       │
│ Embeddings          │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Similarity Engine   │
│                     │
│ Cosine Similarity   │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Recommendation      │
│ Engine              │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ MongoDB / Dataset   │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Ranked Projects     │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ React Recommendation│
│ Interface           │
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│ Student Selects     │
│ Project              │
└─────────────────────┘
```

---

# 18. 🎯 Final User Journey

The complete user experience can be summarized as:

**Discover → Search → Understand → Recommend → Explore → Compare → Select → Plan → Develop**

```text
Discover ProjectMind AI
          ↓
Describe Your Idea
          ↓
AI Understands Your Requirement
          ↓
Get Personalized Recommendations
          ↓
Compare Projects
          ↓
Explore Details & Resources
          ↓
Save Your Favorite
          ↓
Select Your Project
          ↓
Generate Roadmap
          ↓
Identify Skill Gaps
          ↓
Follow Learning Path
          ↓
Build Project
          ↓
Generate Documentation
          ↓
Prepare for Interview
```

---

# 19. 📌 Feature Roadmap Summary

| Category           | Current |        Future |
| ------------------ | ------: | ------------: |
| NLP Recommendation |       ✅ |      Advanced |
| Semantic Search    |       ✅ |      Improved |
| Smart Filtering    |       ✅ |  Personalized |
| Project Details    |       ✅ |      Advanced |
| Favorites          |       ✅ |   Collections |
| Search History     |       ✅ |     Analytics |
| Similar Projects   |       ✅ | AI Similarity |
| Skill Gap Analysis |       ✅ |     Advanced |
| Uniqueness Checker |       ✅ |     Advanced |
| Analytics          |       ✅ |     Advanced |
| AI Roadmap         |       ✅ |      Advanced |
| Synopsis Generator |       ✅ |      Advanced |
| AI Chat Assistant  |       ✅ |      Streaming |
| Learning Path      |       ✅ |      Curated |
| Team Builder       |       ✅ |      Advanced |
| PDF Generator      |       ✅ |     Full report |
| Voice Search       |       ✅ |      Multi-lang |
| Multi-language     |       ❌ |             ✅ |
| Mobile App         |       ❌ |             ✅ |
| AI Interview Prep  | Dropped |  Covered by Chat Assistant |

*(Rows for Skill Gap Analysis, Uniqueness Checker and Analytics were corrected from ❌ to ✅ —
see the implementation status note at the top of this file.)*

---

# 🎓 Project Goal

The ultimate goal of **ProjectMind AI** is not only to recommend project topics but to become a complete AI assistant that helps students go from:

> **"I don't know what project to make."**

to

> **"I have selected my project, know what to learn, have a complete roadmap, and know how to build and present it."**
