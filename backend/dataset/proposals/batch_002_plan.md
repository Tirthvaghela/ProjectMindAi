# Batch 2 proposal (NOT IMPORTED)

**Status: proposal only.** Nothing here has been written to MongoDB or to
`projects_seed.json`. The live and seed catalogues are still 868 projects
(`pm-001`–`pm-868`). No evaluation numbers exist for a 1,020-project catalogue and
none are claimed.

* Candidates: `dataset/candidates/batch_002/*.json` (152 ideas, 18 files by domain)
* Read-only dry run: `dataset/reports/batch_002.plan.json`
  (`python -m scripts.import_catalogue --batch batch_002 --min-description 170`)
* Dry-run result: 152 approved (would be `pm-869`–`pm-1020`), 0 rejected,
  0 duplicate ids/titles, 0 schema problems, 5 flagged for human review.

## What was authored, and what was removed

186 ideas were written across the 14 domains; 34 were removed, leaving 152.

* 7 were rejected by the importer as near-duplicates (similarity ≥ 0.88) of
  existing projects: Website Performance Budget Monitor, Particle Filter
  Localisation, GitOps Continuous Deployment, Occupancy Grid Mapping,
  Differential-Drive Odometry, Sudoku Solver with Constraint Propagation and Model
  Drift Monitor.
* 27 more were dropped by hand after scoring 0.82–0.87 against Batch 1 projects
  (e.g. Feature Flag Service, Hand-Tracking Piano, Voice Notes, Robot Arm
  Kinematics, Market Basket Analysis, Active Learning Assistant, Sign Language
  Recogniser) because they were weakly differentiated.
* Descriptions under 170 characters were lengthened with concrete deliverables
  rather than padded.

The surviving ideas each name a different mechanism, dataset or constraint.
Titles that only swap a domain noun into an existing pattern were rejected.

## Distribution (this batch only)

| Domain | n | | Difficulty | n |
|---|---|---|---|---|
| Data Science | 19 | | Beginner | 43 (28%) |
| Artificial Intelligence | 14 | | Intermediate | 67 (44%) |
| Natural Language Processing | 13 | | Advanced | 42 (28%) |
| Computer Vision | 12 | | | |
| Machine Learning | 12 | | Duration | |
| Internet of Things | 12 | | 3–5 weeks | 27 |
| Deep Learning | 10 | | 6–8 weeks | 61 |
| Web / Mobile / Cloud & DevOps | 9 each | | 9–11 weeks | 51 |
| AR & VR | 9 | | 12–13 weeks | 13 |
| Blockchain / Cybersecurity / Robotics | 8 each | | | |

Projected 1,020-project catalogue (dry run): Beginner 208, Intermediate 467,
Advanced 345. Every domain is between 53 and 92 projects.

## Gaps this batch targets (from the pre-batch audit)

* **Non-Python stacks.** The pre-batch audit found few non-Python stacks. This batch adds Prolog,
  R (5), C++ (8), Rust (4), Go (4), Kotlin (6), C# (7), Swift, Java, Dart, Solidity,
  SQL-first and C-for-microcontroller projects. Python still appears in about half
  (78 of 152), mostly because data work is Python-centric.
* **Evidence-first project types** (calibration studies, user studies, benchmarks,
  fault-injection, fairness audits), which students rarely see in catalogues.
* **Short and long durations.** 3–5 week beginner and 12–13 week advanced items,
  both thin in Batch 1.
* **Beginner depth** in Data Science, NLP, Cybersecurity and Blockchain.

## Quality criteria (enforced by the importer unless marked manual)

1. Description 170–450 characters, specific, and states what is built, how it is
   judged and one deliverable. No marketing language. *(automatic)*
2. 2–6 technologies, named as students would search for them. *(automatic)*
3. Difficulty and duration plausible together (Beginner 3–8 wks, Intermediate
   5–12, Advanced 7–14). *(automatic)*
4. No semantic near-duplicate: reject ≥ 0.88, human review 0.80–0.88. *(automatic)*
5. Unique title; schema valid; ids continue from the catalogue maximum. *(automatic)*
6. Realistic for a student with commodity hardware; no paid services required
   beyond free tiers; safe/ethical scope for security, robotics and health ideas.
   *(manual)*
7. No factual claim a student could not verify (e.g. no invented datasets or
   accuracy numbers). *(manual)*

## Five items flagged for human review (0.80–0.85 similarity)

| Candidate | Closest existing | Sim | Suggested decision |
|---|---|---|---|
| Customer Segmentation with RFM and Clustering in R | pm-252 RFM Segmentation | 0.818 | Keep: R and Shiny angle is the point; reviewer to confirm |
| Edge Gateway that Buffers Data During Outages | pm-730 Store-and-Forward Telemetry Gateway | 0.800 | Likely drop (same idea) |
| Home Network Port Scanner and Exposure Report | pm-447 Port Scanner and Service Fingerprinting | 0.809 | Keep only if framed as exposure reporting |
| Log-Based Intrusion Detection with Sigma-Style Rules | pm-448 Log Analysis for Intrusion Indicators | 0.803 | Reviewer decision |
| Plant Disease Spotting on Leaf Photos with Honest Field Tests | pm-048 Plant Disease Identification | 0.811 | Keep: domain-shift study is distinct |

The importer treats flagged items as approved unless the reviewer removes them
from the batch files before `--apply`. These are suggestions, not decisions.

## Technologies the catalogue has not seen yet

The dry run warns that dozens of technology names are new to the alias table
(for example Rust, Prolog, Weka, Apache Spark, dbt, Axum, Yjs). Before import,
add the ones students would search for to `nlp/skills.py` so technology-aware
retrieval can match them, then re-run `scripts.alias_audit`. Leaving them out is
safe (they are simply not matched), but weakens the retrieval benefit.

## Steps before and after import

Needs a human:
1. Review the 5 flagged items and spot-check ~30 random descriptions for accuracy.
2. Decide whether to import; run `--apply` only after reviewing the printed plan hash.

Mechanical (existing tooling, none run yet):
3. `scripts.import_catalogue --batch batch_002 --apply` (backup, insert-only,
   rollback manifest) → seed file regenerated from the reviewed plan.
4. `scripts.catalogue_audit`; backend and frontend test suites.
5. `scripts.eval_next_version prepare --version v3` (works only once the catalogue
   has changed), have a **different** person grade the new pool, then
   `build --version v3 --annotator <name>`.
6. Evaluate old and new rankers on v3; only then quote metrics for the larger
   catalogue. Do not compare v3 numbers with the 868-project v2 numbers.

## Out of scope

No database write, no seed edit, no change to existing project records or IDs, no
evaluation numbers for the 1,020-project catalogue.
