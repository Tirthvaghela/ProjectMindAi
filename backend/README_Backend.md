# ProjectMind AI — Backend

Semantic project recommendation API. Flask + MongoDB + hybrid retrieval.

## Setup

Prerequisites: **Python 3.11**, **MongoDB** running on `localhost:27017`.

```powershell
cd backend
python -m venv venv
venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```

Install PyTorch from the CPU index first — the default PyPI wheel bundles CUDA
(~2.5 GB) that this project never uses. The CPU wheel is ~120 MB.

## Running

```powershell
venv\Scripts\python -m scripts.seed_db        # load dataset into MongoDB
venv\Scripts\python -m scripts.build_index    # compute embeddings (downloads model, ~90 MB)
venv\Scripts\python app.py                    # serve on http://127.0.0.1:5000
```

Check it came up: `curl http://127.0.0.1:5000/api/health`

Re-run `build_index` whenever the project collection changes.

### Running in production

`python app.py` is Flask's development server — fine for local work, not
designed to hold up under concurrent load, and `FLASK_DEBUG=1` must never be
set outside local development (the Werkzeug debugger it enables can execute
arbitrary code from the browser on an unhandled exception). Use a real WSGI
server instead:

```powershell
venv\Scripts\python -m pip install waitress
venv\Scripts\waitress-serve --host=127.0.0.1 --port=5000 app:app
```

Waitress is pure Python — no C extensions to build, which is why it's the
pick here over gunicorn (Unix-only) for a project developed on Windows.

## Scripts

| Command | Purpose |
|---|---|
| `python -m scripts.seed_db` | Load `dataset/projects_seed.json` into MongoDB (idempotent upsert) |
| `python -m scripts.seed_db --replace` | Wipe the collection first |
| `python -m scripts.build_index` | Rebuild the embedding index |
| `python -m scripts.validate_dataset` | Schema + duplicate checks |
| `python -m scripts.validate_dataset --check-links` | Also verify URLs resolve |
| `python -m scripts.evaluate` | Retrieval metrics against labelled queries |
| `python -m scripts.evaluate --sweep` | Ablation over dense/sparse weights |
| `python -m scripts.smoke_search` | Eyeball ranked results for sample queries |

## Tests

```powershell
venv\Scripts\python -m pytest tests/ -v
```

442 tests. Most are pure-function unit tests needing no fixture at all —
`db/schema.py`, `nlp/preprocess.py`, `nlp/generator.py`, `nlp/team_builder.py`,
`nlp/timeline.py`, `nlp/learning_path.py`, `nlp/resume.py`, and
`nlp/similarity.py` (the query-encoding step there is monkeypatched to a
hand-picked vector rather than loading the real embedding model, so those
tests stay fast). The `test_*_routes.py` files (including `test_idea_routes.py`
and `test_teams_routes.py`) and `test_auth.py`/`test_teams.py` genuinely touch
MongoDB, via the `mongo_test_db` fixture in `conftest.py`, which redirects to
a throwaway `projectmind_test` database on the same server and drops it
afterward. Those files skip themselves if `mongod` isn't reachable rather
than failing. A handful of proxied-collection tests (`test_teams.py`) simulate
a `DuplicateKeyError` mid-write to exercise the team-join and invite-code
races without needing real concurrent requests.

## API

All responses are wrapped: `{"data": ...}` on success, `{"error": "..."}` on failure.

Endpoints needing user identity read an `X-Device-Id` header — a UUID the
frontend generates once and stores in `localStorage`. There are no accounts.

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/health` | Per-dependency status; 503 when degraded |
| POST | `/api/search` | `{query, domain?, difficulty?, technologies?, max_duration_weeks?, top_k?, personalize?}` |
| GET | `/api/projects` | Paginated browse: `?limit=&skip=&domain=&difficulty=` |
| GET | `/api/project/<id>` | Single project |
| GET | `/api/project/<id>/synopsis` | Generated synopsis |
| GET | `/api/project/<id>/roadmap` | Generated week-by-week roadmap (phases carry objective/tasks/technologies/expected_output/dependencies) |
| GET | `/api/project/<id>/milestones` | Measurable build checkpoints, derived from the same roadmap |
| GET | `/api/similar/<id>` | Nearest projects by embedding |
| GET | `/api/filters` | Filter options for the UI |
| GET | `/api/analytics` | Aggregate counts + trending searches |
| POST | `/api/skill-gap` | `{project_id, skills[]}` → readiness % |
| POST | `/api/team-builder` | `{project_id, members[]}` → role suggestions |
| POST | `/api/timeline-predict` | `{project_id, team_size?, experience_level?}` |
| POST | `/api/learning-path` | `{skills[]}` → resources per skill |
| POST | `/api/uniqueness` | `{title, description}` → duplicate check |
| POST | `/api/resume-suggest` | Multipart file or `{text}` → ranked projects |
| POST | `/api/recommend` | `{skills[], experience_level?, team_size?, max_duration_weeks?}` → explainable multi-factor ranking (`nlp/recommend.py:personalized_recommend`) |
| POST | `/api/idea/skill-gap`, `/synopsis`, `/roadmap`, `/milestones`, `/timeline`, `/team-builder`, `/chat` | Same tools as their `/api/project/<id>/...` and `/api/skill-gap`/`/api/team-builder` equivalents, but for a generated idea that was never written to Mongo — built via `nlp/generator.py:idea_doc()` from the idea's own fields (title/description/domain/technologies/duration) instead of a catalogue lookup |
| POST | `/api/favorite` | `{project_id}` (idempotent) |
| DELETE | `/api/favorite/<id>` | Remove |
| GET | `/api/favorites` | Full project documents, not just ids |
| GET | `/api/history` | Recent searches |
| DELETE | `/api/history` | Clear |
| POST | `/api/feedback` | `{rating?, message?, project_id?, query?}` |
| POST | `/api/project/<id>/chat` | `{message, history?}` — stateless, project-grounded (see `nlp/ai_assistant.py`) |
| GET / POST | `/api/conversations` | List / create a general chat conversation (device-scoped, persisted) |
| GET / DELETE | `/api/conversations/<id>` | Read / delete one conversation |
| POST | `/api/conversations/<id>/messages` | `{message}` → reply, appended server-side |
| POST | `/api/auth/signup`, `/login`, `/logout` | Email/password accounts, bearer-token sessions |
| GET | `/api/auth/me` | Resolve the current `X-Auth-Token` |
| POST | `/api/teams`, `/api/teams/join` | Create a team workspace (from a `project_id` or a generated `idea`, mutually exclusive) / join by invite code |
| GET | `/api/teams/mine`, `/api/teams/<id>` | List own teams / one team — includes the live `project` context (description/technologies/difficulty/duration/skills) for a project-backed team, or a snapshotted idea for an idea-backed one. `invite_code` is stripped from the payload for everyone except the team's owner. |
| PATCH | `/api/teams/<id>` | `{name}` — rename, owner-only |
| DELETE | `/api/teams/<id>/members/<user_id>` | Owner removes another member, or a member removes themselves |
| POST | `/api/teams/<id>/skills` | `{skills[]}` — a member records their own skills, self-service |
| GET | `/api/teams/<id>/roles` | Role suggestions for the team's real roster + project (`nlp/team_builder.py`, same engine as `/api/team-builder`) |
| GET / POST | `/api/teams/<id>/messages` | Team message board |
| GET | `/api/notifications` | Recent notifications |
| POST | `/api/notifications/<id>/read`, `/read-all` | Mark read |

`/project/<id>/chat` and `/conversations/<id>/messages` are rate-limited
(20/hour and 30/hour respectively) — the only routes that call an external,
cost-bearing API. Both return 503 if `GROQ_API_KEY` is unset.

## How retrieval works

Three decisions worth understanding before changing anything.

**1. Two preprocessing paths, not one.** The common tutorial pipeline
(tokenise → remove stopwords → lemmatise → embed) is wrong for
sentence-transformers. Those models are trained on natural sentences and use
word order and function words for meaning; stripping stopwords collapses "a
project *for* kids *with* disabilities" and "a project *by* kids *with*
disabilities" into the same token bag.

So `nlp/preprocess.py` runs:
- `clean_for_embedding()` — minimal, feeds the transformer
- `tokens_for_bm25()` — full classical pipeline, feeds BM25, which is
  bag-of-words and genuinely benefits from it

**2. Hybrid scoring.** Dense embeddings understand meaning but are weak on rare
exact tokens. Real measured example — query `"YOLOv8"` over 500 projects:

| Result | semantic | keyword | final |
|---|---|---|---|
| Real-Time Object Detection (correct) | +0.299 | 3.31 | 0.947 |
| Pothole Detection from Dashcam Video | +0.241 | 3.71 | 0.853 |
| People Counting for Footfall Analytics | +0.228 | 3.71 | 0.828 |

Semantically those are close; the exact token is what separates them. Measured
over 25 labelled queries at 500 projects (nDCG@5): embeddings alone 0.866,
BM25 alone 0.737, **hybrid 0.892**.

Note the balance shifted when the corpus grew. At 50 projects the optimum was
an even 50/50 split; at 500 it is 80/20 in favour of dense. Hybrid still beats
both pure approaches — see `config.py` for the full sweep and the reasoning.

**3. Personalisation is bounded, not dominant.** When a device has favourites or
recent searches, `recommend.build_profile()` averages those into one unit vector
— saves weighted 1.0, searches 0.4, since a save is an endorsement and a search
is closer to curiosity. The profile then enters the score as a convex blend:

```
fused = (1 - w) * relevance + w * affinity        w = PERSONALIZATION_WEIGHT (0.15)
```

Blended rather than added, so the score stays in [0, 1] and affinity can never
do more than 15% of the work. That is enough to reorder near-ties and
effectively never enough to promote an irrelevant result — the filter-bubble
failure mode where a student who saved three vision projects stops being shown
the NLP project that actually answers their query. A device with no history
gets a profile of `None` and the exact pre-personalisation ranking. Clients can
opt out per request with `{"personalize": false}`, and the response reports what
was applied under `personalization`.

**4. Filter before ranking.** Ranking first and filtering the top N afterwards
routinely returns nothing, because the requested difficulty may not appear in
an unfiltered top 10. `HybridRetriever._mask()` builds a boolean mask over the
corpus first and only ranks survivors.

## Storage layout

MongoDB holds documents; embeddings live in `data/embeddings.npy` with
`data/ids.json` mapping row → `project_id`. Vectors are L2-normalised at build
time so cosine similarity is a plain dot product — 500 × 384 floats is 750 KB
and a full scan is still sub-millisecond. A vector database would add
operational complexity and network latency for no measurable gain at this
scale; revisit somewhere north of 100k records.

Both index files must be written together; row *i* corresponds to `ids[i]`, and
a mismatch silently corrupts every result. `save_index()` and `load_index()`
both assert on this.

## Known issues

- **NLTK import hook.** NLTK 3.10 blocks imports resolving inside the current
  working directory (CWE-427). Since `venv/` lives inside the project, this
  blocks `regex`. `nlp/preprocess.py` sets `NLTK_DISABLE_IMPORT_SECURITY=1`
  before importing NLTK. The hook's suggested fix (`-P` / `PYTHONSAFEPATH`)
  does **not** work here — the check tests filesystem containment, not
  `sys.path`.
- **Recall@5 has a low ceiling now, by construction.** Several evaluation
  queries have 25–50 relevant projects, and five result slots cannot hold them.
  The theoretical maximum Recall@5 across the query set is 0.511; the system
  reaches 0.417, or 82% of what is attainable. Read nDCG@5 and MRR as the
  headline numbers and treat Recall@5 as a diagnostic.
- **`github_url` holds a *reference* repo, not the project's own.** These are
  briefs nobody has built yet, so there is no canonical repo to link. Each
  entry points at the upstream project for that brief's core technology
  (YOLOv8 → `ultralytics`, face recognition → `ageitgey/face_recognition`), and
  the UI labels it "Reference repo" so it is not mistaken for a finished
  solution. All 50 were verified to resolve; re-check with
  `validate_dataset --check-links`.
