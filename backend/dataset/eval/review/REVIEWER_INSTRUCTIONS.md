# Reviewing project relevance — instructions

You are helping check how well a project-search system's relevance labels hold up.
You will receive **one CSV file** (`review_sheet_v2.csv`). Please do not ask for, or
look for, anything else about how it was produced; your independent judgement is the
whole point.

## What each row is

A **query** (what a student typed) and one **project** from a catalogue (title, domain,
difficulty, technologies, description). Decide how well the project answers the query.

## Grades — fill `reviewer_grade` with 0, 1 or 2

Each row repeats the rubric for its query in `grade_2_means` and `grade_1_means`. In general:

| Grade | Meaning |
|---|---|
| **2** | The project directly satisfies what the query asks for. |
| **1** | Related or partly satisfying it (right area but not the specific thing asked for). |
| **0** | Does not satisfy the intent. |

Rules of thumb:

* Judge the **project against the query**, not how good the project is.
* Difficulty and duration only matter when the query itself mentions them (for example
  "beginner NLP project"). A query saying "final year project" is just filler.
* Use the rubric text on the row. If it is silent about a case, use your own judgement and
  say so in the comment.
* Don't search for the project elsewhere. Judge from what is on the row.

## Uncertainty and comments

* If you hesitated between two grades, put `y` in `reviewer_uncertain` (and still give your
  best grade). Honest uncertainty is useful; please don't guess to look decisive.
* `reviewer_comment` is optional. Use it for unclear rubric wording, a project you think is
  misdescribed, or why you chose a borderline grade.

## What not to change

Please edit only `reviewer_grade`, `reviewer_uncertain` and `reviewer_comment`. Don't reorder,
delete, add or rename rows or columns, and don't edit the other cells: a changed sheet is
rejected so that nothing gets silently mismatched. Save as **CSV (UTF-8)**.

## Time

About 150–170 rows, roughly 2–3 minutes per ten rows. Partial sheets are fine: say how far
you got. Grade the rows in order if you can't finish.

## Working independently

If several people are reviewing, please don't compare notes until everyone has finished.
Agreement between reviewers is one of the things being measured.
