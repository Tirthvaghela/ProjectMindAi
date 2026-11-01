# Retrieval evaluation dataset

Two labelled datasets, deliberately kept apart. **Do not compare their numbers directly.**

| | v1 | v2 |
|---|---|---|
| File | `../eval_queries.json` (unchanged) | `eval_queries_v2.json` |
| Catalogue | original 500 projects (`pm-001`–`pm-500`) | 868 projects (`pm-001`–`pm-868`), fingerprinted by SHA-256 |
| Labels | binary "relevant" lists | graded 0 / 1 / 2, plus an uncertainty flag |
| Judged | by the original author, over the 500 | 678 candidates pooled from six systems plus every v1 label, reviewed blind |
| Reproduce | `evaluate --dataset v1 --max-project 500 --technology-weight 0` | `evaluate --dataset v2` |

v1 is the historical baseline (nDCG@5 0.892, Recall@5 0.417, MRR 1.000 over 500
projects, stored in `../reports/eval_v1_500_baseline.json` and reproduced from the
stored index). Run against 868 projects it falls to 0.682 / 0.335 / 0.847, but that
fall is mostly an artefact: v1 never judged the 368 newer projects, so a good new
answer counts as a miss (`../reports/eval_v1_868_artefact.json`).

## Grades

Written per query, from the query text alone, **before** any candidate was viewed
(`judgments_v2/criteria.json`). Difficulty and duration only matter when the
query states them ("beginner NLP project").

* **2** directly satisfies the query intent
* **1** related or partially satisfies it
* **0** does not satisfy it
* a trailing `u` in `judgments_v2/qNN.txt` marks the annotator as uncertain

Metrics are reported as **lenient** (grade ≥ 1, closest to v1's labelling), **strict**
(grade 2) and **graded nDCG** (gain = grade). Each lenient/strict figure also has a
`low`/`high` band: uncertain items are treated as wrong one way, then the other.

## Method

1. `freeze` — pool = top 10 of dense-only, BM25-only, hybrid 0.8/0.2, hybrid
   0.5/0.5, and two technology-aware hybrids, plus every project v1 labelled
   relevant. Frozen in `judgments_v2/pools.json` so judged items can never move.
2. `sheet N` — a blinded, shuffled sheet per query: title, domain, difficulty,
   technologies, description. No project id, rank, score, system name or v1 label.
3. Grades recorded in `judgments_v2/qNN.txt`; `build` checks that every candidate
   was judged exactly once and writes `eval_queries_v2.json`.

## What this is not — read before quoting a number

* **One annotator, not independent.** The grades are from a single AI assistant,
  which also authored projects `pm-501`–`pm-868`. Blinding hides ids and ranks; it
  cannot erase familiarity with the new records. This is recorded in the dataset
  (`annotation.conflict_of_interest`).
* **Pooling assumption.** Anything outside the pool is unjudged and counted as not
  relevant. `judged@5` reports how much of a system's top 5 was ever reviewed
  (1.000 for every configuration tested so far); watch it for new systems.
* **9.6% of labels are uncertain** (65 of 678); the low/high bands show the effect.
* **Small.** 25 queries. Differences of a few hundredths are noise.
* **Agreement with v1** on the 516 old projects that were in the pool: 83% raw,
  Cohen's κ 0.51. 89% of v1's relevant labels are still grade ≥ 1; v1 omitted 42
  projects now graded relevant and 45 of its labels fail the explicit criteria.
  The two are different judgements, not one right and one wrong.
* **Independent review is not done.** No human has reviewed these labels yet; the
  tooling is ready and tested on synthetic data only. See "Independent review" below.

## Independent review (needs people)

`python -m scripts.eval_review export` writes `review/review_sheet_v2.csv`
(165 rows: every uncertain item plus a fixed-seed sample of certain ones, never
pooled together), `review/REVIEWER_INSTRUCTIONS.md` and a **private** key
`review/PRIVATE_review_key_v2.json` (gitignored; keep it away from reviewers). Rows
carry sequential ids and no AI grade, project id, rank or system name.

1. Give each reviewer the sheet and instructions; they fill `reviewer_grade` (0/1/2).
2. `eval_review validate reviewerA.csv reviewerB.csv` — checks completeness and
   tampering (edited static columns are rejected); it never reads the AI grades.
3. `eval_review agreement --reviewer A=a.csv --reviewer B=b.csv [--json out.json]` —
   exact agreement, quadratic-weighted Cohen's kappa, reviewer-vs-AI and
   reviewer-vs-reviewer, majority consensus for 3+. Uncertain and sampled rows are
   reported separately.

Until real reviewer files exist, no independence claim should be made.

## Reproducibility and comparison

* `eval_dataset manifest` / `eval_dataset verify` — `MANIFEST_v2.json` pins SHA-256
  of every frozen input (queries, criteria, pools, judgments, the v1 file) and a
  text hash per project; `verify` exits non-zero on any drift.
* `evaluate --dataset v2 --json out.json` saves a report;
  `evaluate --compare a.json b.json` says whether two reports may be compared
  (same dataset version, catalogue fingerprint, `k`, weights) and otherwise refuses
  with the reason. Different catalogue sizes are never subtracted.
* Comparing the 868 baseline with a future version: evaluate **both** systems on the
  *new* dataset version. `eval_v2_tech_0.25.json` is the 868 baseline; its numbers
  are only comparable to runs against the same 868-project catalogue.

## When the catalogue changes

`evaluate --dataset v2` refuses to run (exit 2) if the catalogue no longer matches
the fingerprint, and `tests/test_eval_v2.py` fails. Never edit v1 or v2.

To start v3 after a real import: `python -m scripts.eval_next_version prepare
--version v3` (refuses with exit 3 while the catalogue is unchanged). It carries v2
grades forward **only** for projects whose text hash is unchanged, pools new
candidates and writes blinded sheets (`sheet --version v3 N`); `build --version v3
--annotator <name>` refuses to finish until every new candidate has a judgment from
a named annotator. Nothing is invented. Batch 2 (`../proposals/batch_002_plan.md`)
has not been imported, so there is no v3 yet.
