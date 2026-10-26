"""Central configuration, read once from the environment.

Everything that differs between machines (Mongo URI, model name, retrieval
weights) lives here so no other module has to know about os.environ.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ[key])
    except (KeyError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


# --- Paths -----------------------------------------------------------------
DATASET_DIR = BASE_DIR / "dataset"
DATA_DIR = BASE_DIR / "data"

SEED_FILE = DATASET_DIR / "projects_seed.json"
EMBEDDINGS_FILE = DATA_DIR / "embeddings.npy"
IDS_FILE = DATA_DIR / "ids.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Database --------------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "projectmind")

COLL_PROJECTS = "projects"
COLL_FAVORITES = "favorites"
COLL_HISTORY = "search_history"
COLL_FEEDBACK = "feedback"
COLL_CONVERSATIONS = "chat_conversations"

# Accounts exist only for teams + notifications — favourites/history/search
# stay purely device-scoped, unchanged, exactly as before accounts existed.
COLL_USERS = "users"
COLL_SESSIONS = "sessions"
COLL_TEAMS = "teams"
COLL_TEAM_MESSAGES = "team_messages"
COLL_NOTIFICATIONS = "notifications"
# One learner-profile document per account; the users collection is untouched.
COLL_PROFILES = "user_profiles"
# Per-account step status for a project roadmap; additive, nothing else reads it.
COLL_ROADMAP_PROGRESS = "roadmap_progress"

# --- Embedding model -------------------------------------------------------
# all-MiniLM-L6-v2: 384 dims, ~80 MB, strong quality/speed trade-off on CPU.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = _env_int("EMBEDDING_DIM", 384)

# --- Hybrid retrieval weights ----------------------------------------------
# Dense embeddings capture meaning; BM25 catches exact technical tokens
# ("YOLOv8", "React") that dense retrieval reliably misses.
#
# These values are measured, not guessed, and they were RE-MEASURED after the
# corpus grew from 50 to 500 projects — the earlier note here predicted that
# would be necessary, and it was.
#
# `python -m scripts.evaluate --sweep` over 25 labelled queries / 500 projects:
#
#   dense  sparse   nDCG@5
#    0.00    1.00    0.737   BM25 only
#    0.35    0.65    0.816
#    0.50    0.50    0.845   <- the old default, tuned at 50 projects
#    0.65    0.35    0.877
#    0.80    0.20    0.892   <- best
#    1.00    0.00    0.866   embeddings only
#
# Two things changed with scale. The optimum moved decisively toward dense, and
# the curve became meaningful: at 50 projects the middle rows differed by ~0.001
# and were pure noise, whereas here the trend is monotonic up to 0.80 and the
# spread is 0.155. Hybrid still beats both pure approaches, so the original
# argument for fusing holds — only the balance moved.
#
# The likely cause is corpus density. With 500 projects many records share
# surface vocabulary ("detection", "prediction", "system"), so lexical overlap
# discriminates less than it did across 50 well-separated records, while
# embeddings keep separating on meaning.
#
# Re-run the sweep again after any further substantial corpus change.
DENSE_WEIGHT = _env_float("DENSE_WEIGHT", 0.80)
SPARSE_WEIGHT = _env_float("SPARSE_WEIGHT", 0.20)

DEFAULT_TOP_K = _env_int("DEFAULT_TOP_K", 10)
MAX_TOP_K = _env_int("MAX_TOP_K", 50)

# --- Personalisation --------------------------------------------------------
# How much a device's own taste profile may move a result, as a fraction of the
# final score: fused = (1 - w) * relevance + w * affinity.
#
# Deliberately small. Personalisation that outranks relevance produces a filter
# bubble — a student who saved three computer-vision projects would stop being
# shown the NLP project that actually answers their query. At 0.15 it reorders
# near-ties and effectively never promotes an irrelevant result.
#
# Set to 0.0 to disable personalisation globally.
PERSONALIZATION_WEIGHT = _env_float("PERSONALIZATION_WEIGHT", 0.15)

# Technology identity. When a query names technologies the catalogue knows
# ("React Flask full stack", "mobile app with React Native"), this share of the
# relevance score is the fraction of those technologies a project actually
# lists. Neither retrieval signal can express that on its own: the dense model
# barely separates framework names (its scores for the 28 projects that really
# use React *and* Flask average 0.11 against a corpus mean of 0.05), and BM25
# tokenises "React Native" into the same `react` it uses for React. Zero
# disables it; queries that name no known technology are not affected at all.
#
# Chosen by measurement, not intuition. On 14 held-out stack queries that are
# NOT in the labelled evaluation set, mean P@5 of "the result lists every
# technology the query names" was:
#
#   weight   0.00   0.10   0.15   0.25   0.40
#   P@5      0.61   0.76   0.81   0.89   0.94
#
# 0.25 is the smallest weight tested that reaches 0.85; 0.40 adds only 0.05 more
# while letting technology identity outweigh the semantic signal. On the v2
# labelled set (868 projects) it changes one query materially (React + Flask:
# lenient nDCG@5 0.45 -> 0.83, strict 0.00 -> 0.83) and leaves the other 24
# untouched. The fusion weights below were deliberately NOT changed. Evidence
# is limited: the held-out queries were written by the same person who chose
# the weight, and the proxy is catalogue metadata, not human relevance.
TECHNOLOGY_WEIGHT = _env_float("TECHNOLOGY_WEIGHT", 0.25)

# Recent searches are a weaker signal of taste than a deliberate save, so they
# contribute proportionally less to the profile vector.
PERSONALIZATION_QUERY_WEIGHT = _env_float("PERSONALIZATION_QUERY_WEIGHT", 0.4)

# Cap on how many recent queries feed the profile. They are encoded in one
# batched call, but an unbounded list would still grow request latency.
PERSONALIZATION_MAX_QUERIES = _env_int("PERSONALIZATION_MAX_QUERIES", 5)

# --- Multi-factor personalized recommendation weights ----------------------
# nlp/recommend.py:personalized_recommend combines up to three independent
# signals into one overall_score: retrieval relevance (always present),
# skill fit (only when the caller gave known_skills), and timeline fit (only
# when the caller gave max_duration_weeks). Whichever signals are actually
# present are renormalised against each other — see the renormalisation in
# personalized_recommend — so these three numbers only express *relative*
# importance, not an assumption that all three are always available.
#
# Relevance is weighted highest because it is the only signal grounded in
# what the student actually asked for; skill/timeline fit refine the
# ordering among relevant results rather than override it.
RECOMMEND_RELEVANCE_WEIGHT = _env_float("RECOMMEND_RELEVANCE_WEIGHT", 0.5)
RECOMMEND_SKILL_WEIGHT = _env_float("RECOMMEND_SKILL_WEIGHT", 0.3)
RECOMMEND_TIMELINE_WEIGHT = _env_float("RECOMMEND_TIMELINE_WEIGHT", 0.2)
# How well a project's own difficulty matches the student's stated experience
# (recommend.difficulty_fit: 100 exact, 75 one level apart, 50 two). Before
# this signal existed the experience level only changed the timeline estimate,
# so picking Beginner vs Advanced in "Best fit for you" returned identical
# rankings. Like the other signals it is renormalised away when not supplied.
RECOMMEND_DIFFICULTY_WEIGHT = _env_float("RECOMMEND_DIFFICULTY_WEIGHT", 0.3)
# Declared project-domain interests from a saved learner profile. A deliberately
# small, relative weight (same renormalised scheme as above) and only present
# when the caller has a profile with interests and gave no explicit domain
# filter, so un-personalised requests are unchanged. NOT tuned on an evaluation
# set — there is no labelled personalisation data; see dataset/eval/README.md.
RECOMMEND_INTEREST_WEIGHT = _env_float("RECOMMEND_INTEREST_WEIGHT", 0.1)
# The weekly commitment the catalogue's durations are implicitly "per": an
# assumption, not a measurement. profiles/personalization.py:pace_adjusted_weeks
# scales estimates by this / the user's own hours for the soft duration
# preference and notes only.
REFERENCE_HOURS_PER_WEEK = _env_int("REFERENCE_HOURS_PER_WEEK", 10)

# Two records above this cosine similarity are treated as the same project.
# Strict on purpose: this drives dataset deduplication, where a false positive
# silently deletes a legitimate project.
DUPLICATE_THRESHOLD = _env_float("DUPLICATE_THRESHOLD", 0.92)

# Threshold for the user-facing "is my idea original?" check. Deliberately
# lower than DUPLICATE_THRESHOLD: a student rewording an existing project in
# their own words should be warned, and a paraphrase typically lands around
# 0.80-0.88 rather than 0.92. Here a false positive merely shows a "similar
# to" list, which is useful information either way.
UNIQUENESS_THRESHOLD = _env_float("UNIQUENESS_THRESHOLD", 0.78)

# --- API -------------------------------------------------------------------
FLASK_HOST = os.environ.get("FLASK_HOST", "127.0.0.1")
FLASK_PORT = _env_int("FLASK_PORT", 5000)
# Defaults OFF. The Werkzeug debugger enabled by debug=True can execute
# arbitrary code from the browser on any unhandled exception — safe for a
# developer who opted in via .env, dangerous as an unnoticed default for
# anyone who deploys this without editing it. Set FLASK_DEBUG=1 locally.
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# Vite dev server defaults; extend via CORS_ORIGINS="http://a,http://b".
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

MAX_HISTORY_PER_DEVICE = _env_int("MAX_HISTORY_PER_DEVICE", 50)

# General (non-project) chat conversations — see nlp/ai_assistant.general_reply.
# Bounded per conversation so a long-running chat can't grow the stored
# document (and the history replayed to the model) without limit.
MAX_CONVERSATIONS_PER_DEVICE = _env_int("MAX_CONVERSATIONS_PER_DEVICE", 100)
MAX_MESSAGES_PER_CONVERSATION = _env_int("MAX_MESSAGES_PER_CONVERSATION", 200)

# --- AI assistant (chat + interview prep) ---------------------------------
# The only LLM-backed feature in this codebase — everything else (search,
# skill_gap, check_uniqueness, generator, team_builder, timeline) is a
# deterministic function over the project's own fields, on purpose. Chat and
# interview-prep genuinely need open-ended generation, so they're the
# exception, gated behind an optional key rather than required to run the app.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

# Optional additional keys to round-robin/fall back across when one hits its
# rate limit — comma-separated, on top of GROQ_API_KEY above. Unset by
# default: a single GROQ_API_KEY behaves exactly as before.
_extra_groq_keys = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
GROQ_API_KEYS = ([GROQ_API_KEY] if GROQ_API_KEY else []) + [k for k in _extra_groq_keys if k != GROQ_API_KEY]

# llama-3.3-70b-versatile (the previous default here) was removed from
# Groq's catalogue — a plain chat completion now 404s with "model does not
# exist or you do not have access to it" on every account, not a quota or
# key problem, so key rotation can't work around it. gpt-oss-20b is Groq's
# current lightweight general-purpose replacement, confirmed working for
# both `reply()`'s prose and nlp/ideation.py's JSON-mode idea generation.
# It is a reasoning model: unlike llama-3.3, part of its output is a hidden
# "thinking" pass that counts against the same max_tokens budget as the
# visible answer — both call sites pass reasoning_effort="low" alongside it
# so that budget isn't silently spent on reasoning before any visible
# content is produced (confirmed live: without it, `reply()`'s max_tokens=600
# was fully consumed by reasoning, returning an empty answer with no error).
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

# Separate model for the tool-calling Dashboard chat (nlp/ai_assistant.py:
# general_reply). Measured directly against this app's tool schemas: models
# that aren't trained for agentic tool use frequently emit a text-based
# pseudo tool call ("<function=search_projects>{...}</function>" inside
# `content`) instead of a native tool_calls entry, which Groq's own validator
# then rejects outright — observed on real turns in this app's exact flow,
# not a hypothetical. gpt-oss-120b was trained specifically for agentic tool
# use and produced clean, correctly-typed native tool calls on the same
# schema every time it was tested. GROQ_MODEL (above) is untouched for
# `reply()`, which never calls a tool and has no such reliability problem.
GROQ_TOOL_MODEL = os.environ.get("GROQ_TOOL_MODEL", "openai/gpt-oss-120b")

AI_ASSISTANT_ENABLED = bool(GROQ_API_KEYS)

# --- Email notifications (optional) ----------------------------------------
# Same trade-off as the AI assistant above: a notification is always stored
# in-app (see notify.py) whether or not this is configured. SMTP only adds a
# second delivery channel on top — nothing breaks, and nothing is required
# to run this app, if these are left blank.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER).strip()
SMTP_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)
