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
- `multiselect` — select-all-that-apply (Moodle `multichoice` with `single=0`):
  `{"name","text","options":[{"text","correct"}],"threshold","generalfeedback","points"}`.
  Each correct tick scores `1/threshold` and each wrong tick `-1/threshold`, so a
  guess cancels a right answer and `threshold` correct ticks earn the full mark
  (Moodle clamps the grade to [0, max], so it can neither exceed full marks nor
  go negative). `threshold` defaults to the number of correct options. Used for
  the HT2026 Vetenskaplighet section, whose author set a per-question threshold.
  The older PVT15 `multichoice` item (pool dict + `points`) is unchanged.
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
**Images.** An item may carry `image` (or `images`) — a path to a file. The
question text references it as `@@PLUGINFILE@@/<filename>`; the builder writes
the Moodle file records into `files.xml` (component `question`, filearea
`questiontext`, itemid = the question id, plus the directory record) and stores
the blob at `files/<sha1[:2]>/<sha1>`, mirroring a real export.

**Comment boxes.** `comment_boxes` is a list of
`{heading, name, category, text, after_section}`; each becomes a 0 p essay in
its own quiz section, placed after the last slot of `after_section` (None = very
end of the quiz). Default (PVT15, IDSV resit) = one trailing box. `same_page`
keeps a box inside its area's own quiz section instead of opening a new one —
a Moodle section always starts a page, so this is what puts the box on the same
page as the question (HT2026: the programming and Vetenskaplighet boxes; the
theory box spans many pages and keeps its own). The HT2026
exam passes one per graded area (theory / programming / Vetenskaplighet). A box
whose `after_section` has no questions is an error.

`comment_intro` (optional `{heading, name, lead_sv, lead_en}`) adds a 0 p
description as the very first slot of the quiz, listing which questions belong
to which comment box ("Frågorna 1–27 → kommentarrutan för teoridelen (fråga
28)"), and appends the same span to each box's own text. The spans are computed
from the section order as **display numbers** — Moodle numbers answerable slots
and skips `description` blocks — so they match what the student sees. Each box
supplies its `area_sv`/`area_en` label. Needs `essays_last=False`.

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
    [--seed N] [-o out.mbz] [--config courses/idsv.json]
```
`--seed` defaults to the config's `seed`, else 570028735. A config may set
`"extends": "<sibling config>"` and override single keys — the HT2026 exam runs
three groups off one base (`courses/idsv_ht2026.json`) plus
`idsv_ht2026_g{1,2,3}.json`, which differ only in seed, machine artifacts,
`coderunner_mbz` and `coderunner_name`.
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
  CodeRunner question (`coderunner_mbz` config path, optional `coderunner_name`
  when one export holds several) when a plan entry sets `coderunner`. Export
  from Moodle as a **course backup with the question bank** (`.mbz` holding
  `questions.xml`), not "Question bank → Export → Moodle XML".
- Plan entries also take content written straight into the config: `items`
  (ready-made item dicts for hand-written questions that don't come from the CSV
  pool) and `info_html` (`[{"name", "html"}, …]`), which emits raw-HTML
  description blocks before the question — the Programmering section uses it for
  the Python-reference cheat-sheets (`courses/idsv_prog_lists.html`,
  `idsv_prog_strings.html`, `idsv_prog_keys.html` = special characters on a
  Swedish Windows/Mac keyboard).
- `idsv_authored.py` — questions written for the exam rather than drawn from
  the CSV (`courses/idsv_ht2026_authored.json`, Peter's HT2026 set). Each spec
  has a `kind`: `term` (massive glossary dropdown; `pool_answer` names the exact
  glossary entry, appended to the pool when new), `value` (full numeric value
  space), `choice` (its own small option list, author's order), `short` (text box
  + accepted answers), `essay`. `image` adds a picture to the question. The pool
  is extended once, before any section is built, so every dropdown in the exam
  shows the same menu. A spec also carries `bank` (`{type, subject}`, plus
  `appendix` when the question needs a figure) — the row it becomes once the
  exam is over, see below; the four Vetenskaplighet `items` in the config carry
  the same key.
- `scripts/extract_pool.py` — (re)extract the glossary pool from an old `.mbz`.
- `scripts/gen_machine.py` — generate the per-group machine problems (appendix,
  questions, answer key) into the exam working folder.
- `scripts/build_ht2026.sh` — build all three HT2026 groups and validate them.
- `scripts/validate_mbz.py` — offline checks on a built `.mbz` (see Validation).
- `scripts/export_bank_rows.py` — after the sitting, fold the exam back into the
  idsv-old-exams bank (see below).
- `courses/idsv.json` — config: paths, points, `overrides`, and the per-chapter
  plan. `courses/idsv_ht2026*.json` — the HT2026 exam (three groups).

## HT2026 exam (2026-09-26, three groups 08–11 / 12–15 / 16–19)
Theory 27 p + programming 5 p + Vetenskaplighet 4 p = 36 p, same grade
thresholds. Chapters 8 and 9 are not examined this year. Each group config names
its own seed, machine artifacts and CodeRunner export (g1 Parlamentsval, g2
Kaféet, g3 Tanta). `chapters` maps a chapter number to that group's content:
`authored` (ids from the authored file), `essay_ids` (CSV ids — the GAI-26
Generative-AI questions) and `dropdowns` (how many bank fillers to draw).
Selection rules baked into the assignment: Peter's per-chapter counts and
exclusions, "alla skall få" (5.1, 5.2, 6.1 in every group), "helst 4.12", and at
most 2 of the 3 groups per question — bank fillers cover the shortfall (ch1 in
g2, ch11 in g3) and can't repeat a concept already used.

Config paths currently point at `~/idsv-old-exams` (CSV) and the exam working
folder `~/Downloads/iexam-dsv-uppsamling` (machine artifacts, course-452 mbz).

## After the exam: back into the question bank
A held sitting becomes old-exam material. `scripts/export_bank_rows.py` rebuilds
each group, walks the finished quiz and writes one CSV row per question examined
into `~/idsv-old-exams/question_bank/2025-08-31.csv`, tagged with the sitting
(`2026gA`/`gB`/`gC`, following the 2025 tags). Questions that came *from* the
bank only gain the tag; `q#` is the number the student saw (Moodle numbers
answerable slots and skips info blocks) from the first group that asked it.
Untouched rows are written back byte for byte, so the diff is only what changed.

```
python scripts/export_bank_rows.py --date 2026-09-26 \
    --exam courses/idsv_ht2026_g1.json 2026gA 08:00 11:00 \
    --exam courses/idsv_ht2026_g2.json 2026gB 12:00 15:00 \
    --exam courses/idsv_ht2026_g3.json 2026gC 16:00 19:00 [--dry-run]
```

Row content comes from the authoritative source per question: the authored JSON
spec (its `bank` key gives the CSV `type`/`subject`), the config `items`, the
machine toolkit's own question/answer-key files, and the CodeRunner text out of
the built backup. Two things the script can't do and that belong to the same
job: copy the group's machine appendix into the bank as
`appendixes/machine-<tag>.tex` (it prints the names it referenced), and add any
new `subject` code to the bank's `models.py`.

## Validation
No live Moodle here; validate by parsing every XML in the `.mbz`, checking
`[[N]]` ranges, machine answers, id uniqueness, and that quiz slots resolve to
question entries. Restore-test on iLearn/iexam before use.
