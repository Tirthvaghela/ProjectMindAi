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

`requirements.txt` is the loose, top-level spec (what this project actually
depends on, `~=` version bands); `requirements.lock.txt` is its fully pinned
transitive closure, for a reproducible install (`pip install -r
requirements.lock.txt` instead of `requirements.txt`). Regenerate it from a
**clean** venv built only from `requirements.txt` (+ the CPU torch index
above) — not a plain `pip freeze` of an existing dev venv, which can quietly
carry unrelated packages installed for something else along with it.

## Environment Variables

`.env.example` (copied above) is the source of truth, with every variable's
default/placeholder and a comment on what it does — see the root
[`README.md`](../README.md)'s own Environment Variables table for the full
list at a glance. Nothing is required beyond MongoDB itself; every
`GROQ_*`/`SMTP_*` block is optional and the app runs fully without it.

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
venv\Scripts\waitress-serve --host=127.0.0.1 --port=5000 app:app
```

(`waitress` is already in `requirements.txt`/`requirements.lock.txt` — no
separate install needed.)

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
| `python -m scripts.import_catalogue --batch batch_001` | **Dry run** of a catalogue expansion: validate candidates in `dataset/candidates/<batch>/`, reject exact and semantic duplicates, assign ids, write a reviewable plan to `dataset/reports/` |
| `python -m scripts.import_catalogue --batch batch_001 --apply` | Apply the reviewed plan: append to the seed file and insert-only into MongoDB (existing documents are never modified), backing up first; idempotent |
| `python -m scripts.import_catalogue --rollback batch_001 [--apply]` | Undo a batch by its manifest (dry run unless `--apply`) |
| `python -m scripts.catalogue_audit` | Read-only audit of a catalogue file: id stability, duplicates, missing metadata, distributions (`--file`, `--semantic`, `--json`, `--strict`) |

## Tests

```powershell
venv\Scripts\python -m pytest tests/ -v
```

The suite (pytest prints its size). Most are pure-function unit tests needing no fixture at all —
`db/schema.py`, `nlp/preprocess.py`, `nlp/generator.py`, `nlp/team_builder.py`,
`nlp/timeline.py`, `nlp/learning_path.py`, `nlp/resume.py` (including
`test_resume_parsing.py`'s real, hand-built PDF/DOCX fixtures for the actual
file-parsing path — not just the pure skill-detection functions downstream
of it), and `nlp/similarity.py` (the query-encoding step there is
monkeypatched to a hand-picked vector rather than loading the real embedding
model, so those tests stay fast). The `test_*_routes.py` files (`test_idea_routes.py`,
`test_teams_routes.py`, `test_search_routes.py`, `test_projects_routes.py`,
`test_health_route.py`) and `test_auth.py`/`test_teams.py`/`test_build_retriever.py`
genuinely touch MongoDB, via the `mongo_test_db` fixture in `conftest.py`,
which redirects to a throwaway `projectmind_test` database on the same
server and drops it afterward. Those files skip themselves if `mongod` isn't
reachable rather than failing. A handful of proxied-collection tests
(`test_teams.py`) simulate a `DuplicateKeyError` mid-write to exercise the
team-join and invite-code races without needing real concurrent requests.
`test_embeddings.py` exercises the on-disk vector index (save/load,
corruption, missing files) against a `tmp_path`, never the real
`data/embeddings.npy`. `test_rate_limits.py` and
`test_ai_assistant.py::test_model_status_*` assert configuration/behaviour
directly (Flask-Limiter's `limit_manager`, a faked `models.list()`) rather
than by hammering a route for a real 429 — rate limiting is only verified to
enforce correctly under waitress, not the dev server used here (see
`extensions.py`).

## API

All responses are wrapped: `{"data": ...}` on success, `{"error": "..."}` on failure.

Two independent identity headers, not one — see `routes/helpers.py`:
`X-Device-Id` (a UUID the frontend generates once and stores in
`localStorage`) scopes anonymous favourites/history/personalisation/chat and
needs no account; `X-Auth-Token` (a bearer session token from
`/api/auth/login`/`/signup`) identifies a signed-in account and is required
only for teams and notifications. Most routes need at most one of the two,
never both — see the root [`README.md`](../README.md)'s "Known Limitations"
section for the trade-off that anonymous identity model makes.

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/health` | Per-dependency status; 503 when degraded. `ai_assistant.model_status` is a cached (5 min), `models.list()`-based reachability check for the configured Groq model(s) — costs no completion tokens, never affects the top-level status. `search_index.stale` compares MongoDB's live project count against the retriever's indexed count, no rebuild triggered. |
| POST | `/api/search` | `{query, domain?, difficulty?, technologies?, max_duration_weeks?, top_k?, personalize?}` |
| GET | `/api/projects` | Paginated browse: `?limit=&skip=&domain=&difficulty=` |
| GET | `/api/project/<id>` | Single project |
| GET | `/api/project/<id>/synopsis` | Generated synopsis |
| GET | `/api/project/<id>/roadmap` | Generated week-by-week roadmap (phases carry objective/tasks/technologies/expected_output/dependencies) |
| GET | `/api/project/<id>/milestones` | Measurable build checkpoints, derived from the same roadmap |
| GET | `/api/similar/<id>` | Nearest projects by embedding |
| GET | `/api/filters` | Filter options for the UI |
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

Rate limits (`extensions.py`; see its own comment on why they only enforce
correctly under waitress, not the dev server) opt in per route rather than a
blanket default — either a real external cost, or otherwise expensive/
abusable with no auth to fall back on:

| Route | Limit | Why |
|---|---|---|
| `/project/<id>/chat`, `/idea/chat` | 20/hour | Calls Groq (external, cost-bearing) |
| `/conversations/<id>/messages` | 30/hour | Calls Groq |
| `/search`, `/recommend` | 30/minute | Hybrid retrieval — real, if bounded, CPU cost |
| `/uniqueness` | 20/minute | Embeds + scores against the whole catalogue |
| `/resume-suggest` | 10/minute | File parsing (PDF/DOCX) |
| `/team-builder`, `/idea/team-builder` | 30/minute | Unauthenticated, unbounded-looking `members` list |
| `/teams/<id>/messages` | 30/hour | Triggers a notification (and optionally an email) to every teammate |
| `/notifications`, `/notifications/<id>/read`, `/notifications/read-all` | 60/minute | Defense-in-depth floor, not a real cost — generous enough for the 30s poll `NotificationsBell.jsx` already does |
| `/auth/signup` | 10/hour | Security-sensitive |
| `/auth/login` | 20/hour | Security-sensitive |

Every route that calls Groq returns 503 if `GROQ_API_KEY` is unset. Every
other route in this table — favourites, history, feedback, teams (besides
messages), auth's `/me`/`/logout` — has no rate limit at all: cheap,
authenticated-or-ownership-checked reads/writes, the same category as the
rest of this API.

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
*(Historical: v1 labels, original 500 projects, reproduced by
`evaluate --dataset v1 --max-project 500 --technology-weight 0`. For the current
868-project catalogue see `dataset/eval/README.md` — the two are not comparable.)*

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

## "Best fit for you" semantics

`POST /api/recommend` (`nlp/recommend.py:personalized_recommend`). These rules
are pinned by `tests/test_recommend_constraints.py` and
`tests/test_deadline_and_scale.py`; change them deliberately, with tests.

- **Hard constraints exclude**: `domain`, `difficulty`, `technologies` and
  `max_duration_weeks`. **Preferences rank**: relevance, skill readiness and
  `experience_level`.
- **Experience level is a ranking preference, not a filter.** It scores
  `difficulty_fit`: 100 for an exact match, 75 one level apart, 50 two apart,
  weighted by `RECOMMEND_DIFFICULTY_WEIGHT` (default 0.3) alongside the
  relevance (0.5), skill (0.3) and timeline (0.2) weights. Signals that are not
  supplied are dropped and the rest renormalised. A below-level project is
  explained as such, never presented as an exact match.
- **Max weeks is compared with the *estimated* duration** for the chosen team
  size and experience (`nlp/timeline.py`), not the solo baseline. A project with
  no known duration (missing, null, zero, negative, non-numeric) is **never**
  reported as fitting a deadline; the response carries
  `excluded_unknown_duration` (a count) when a deadline was applied. `/api/search`
  follows the same rule. An unusable deadline (`"soon"`, `0`, `2.5`, `true`) is
  a 400, not silently ignored or truncated.
- **Team size only changes the estimate.** The catalogue has no team-size
  field, so there is no per-project team compatibility check.
- **Skill readiness uses the shared alias table** (`nlp/skills.py`), added on
  top of the older token matching: whole names only, so `sklearn` = `scikit-learn`
  and `node` = `Node.js`, but `Java` never matches `JavaScript`. Ambiguous
  abbreviations (`ts`, `np`, `torch`, `py`, `next`, `.net`) are deliberately not
  aliases. Keyword explanations show the words the user typed / canonical
  names ("pandas"), not lemmas ("panda"); matching still uses lemmas.
- **Deterministic**: equal scores are ordered by `project_id`.
- **Known gap**: skill readiness (project skills + technologies, alias-aware)
  and keyword matching (BM25 lemmas) are separate signals and can disagree.

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
