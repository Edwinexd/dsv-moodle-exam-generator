# AGENTS.md — dsv-moodle-exam-generator

Builds Moodle 4.5 `.mbz` exam backups from a question pool. Stdlib only (no venv
needed). Two entry points:

- `generate.py` — original PVT15-style exam (multiple choice + essays).
- `build_idsv.py` — IDSV resit/uppsamling exam (unified dropdowns + machine
  language + CodeRunner). See below.

## Core builder: `moodle_backup_builder.py`
`MoodleBackupBuilder` writes the whole `.mbz` (course/section/module, gradebook,
info + disclaimer labels, news + Q&A forums, SEB lockdown, Bologna grade
boundaries, comment box, quiz).

Question model is a generic **item** list per section. Each item has a `qtype`:
- `multichoice` — `{"q": <pool dict>, "points"}`
- `gapselect` — unified dropdown: `{"name","text","options"[],"answer_index","generalfeedback","points"}`. The text must contain `[[N]]` where N == `answer_index` (1-based index into `options`); fraction is unused, all options share group 1.
- `essay` — `{"name","text","points","raw_text"?}`
- `description` — `{"name","text"}` (0p, no plugin block)
- **verbatim** (any qtype, e.g. `coderunner`) — an item carrying a `plugin_xml`
  key bypasses the per-qtype renderers: the plugin block is reused untouched and
  `text`/`generalfeedback` arrive pre-escaped (`raw_text`/`raw_feedback` default
  True). Produced by `mbz_extract.extract_question(mbz, qtype, name=None)`, which
  lifts a question verbatim from an exported `.mbz` and picks the version with
  the latest `<timemodified>` (a full-course export stores every version and NOT
  in version order — the newest can come first, so file order is unreliable).

Back-compat: a section with the old `mc_questions`/`essay` keys is auto-normalised
to items. `essays_last=True` (default) groups all essays after the MC (PVT15
layout); `build_idsv.py` sets `essays_last=False` to keep section order.
Every question carries empty `plugin_qbank_comment_question` /
`plugin_qbank_customfields_question` wrappers (4.5 export fidelity).

**Grades & display.** `grade_letters` is a list of `(letter, min_points)`
absolute thresholds (default = Bologna % of the total, PVT15). `embed_grade_feedback`
(default True) controls whether per-grade quiz feedback + gradebook grade-letters
are baked in; IDSV sets it False (criteria live only in the info label, like the
old exam). `programming_min_points` adds the "≥N p on the programming task" note.
Pass mark = lowest non-F/FX threshold. **`reviewmaxmarks` always includes the
during-attempt bit** so the available marks per question are visible while sitting
the exam (the achieved score still follows the after-close review setting).
`answer_guidance` (optional `(sv, en)` tuple, default None) inserts a note in the
info label just before the "a question score can never go below 0" line — used by
IDSV for "answers must be short and concise…"; other exams leave it None.

`gapselect` items honour a `shuffle` flag (default True); numeric dropdowns whose
answer ranges over a small fixed space (hex byte, 8-bit binary) list every value
sorted with shuffle off — see `idsv_questions.numeric_options`. Glossary term
dropdowns are sorted alphabetically by the English term (`english_sort_key`:
the trailing parenthetical of "Svenska (English)") with shuffle off. **RNG
determinism:** the old per-question `rng.shuffle` is kept before the sort so the
question *draw* stays identical across builds — do not remove it or the
selection shifts.

**Pagination.** Up to `MC_PER_PAGE` (5) items per page, new page at every
section/heading boundary. A `coderunner` normally gets its own page, **except**
when it directly follows its own info-block `description`(s) in the same section —
then it shares their page (Python operations reference stays beside the
programming task, like the old exam).

## IDSV resit build
```
python build_idsv.py --date YYYY-MM-DD --start HH:MM --end HH:MM \
    [--seed 570028735] [-o out.mbz] [--config courses/idsv.json]
```
Pieces (all single-pass, no DB):
- `idsv_questions.py` — CSV → dropdown/essay items. `sa`/`sc`/short "essay" rows
  become dropdowns; term answers use the shared glossary pool, numeric answers
  list their full fixed value space, `sc` uses its own `ans_alt_*`. Long answers
  → essays. Config `overrides` (keyed by CSV id) patch a single drawn question:
  `answer` replaces the correct option's text, `text_sub` applies
  `[[regex, repl], …]` to the question body; the build errors if an override id
  wasn't drawn (seed/selection changed).
- `idsv_machine.py` — machine-language section: static ISA description
  (`courses/idsv_machine_isa.html`, reused verbatim) + config description (memory
  /register tables) + one numeric dropdown per asked value (R3/R1/PC). Reads the
  generated artifacts in the exam working folder; answers come from the answer-key
  file (machine/ toolkit, seed in the key).
- `mbz_extract.py` — generic, lifts any question verbatim from an exported
  `.mbz` (see the verbatim item above). `build_idsv.py` uses it for the new
  CodeRunner question (`coderunner_mbz` config path) when a plan entry sets
  `coderunner`. A plan entry's `info_html` (`[{"name", "html"}, …]`) emits
  raw-HTML description blocks before it — the Programmering section uses it for
  the two Python-reference cheat-sheets (`courses/idsv_prog_lists.html` /
  `idsv_prog_strings.html`, mirroring the old exam).
- `scripts/extract_pool.py` — (re)extract the glossary pool from an old `.mbz`.
- `courses/idsv.json` — config: paths, points, `overrides`, and the per-chapter
  plan.

Config paths currently point at `~/idsv-old-exams` (CSV) and the exam working
folder `~/Downloads/iexam-dsv-uppsamling` (machine artifacts, course-452 mbz).

## Validation
No live Moodle here; validate by parsing every XML in the `.mbz`, checking
`[[N]]` ranges, machine answers, id uniqueness, and that quiz slots resolve to
question entries. Restore-test on iLearn/iexam before use.
