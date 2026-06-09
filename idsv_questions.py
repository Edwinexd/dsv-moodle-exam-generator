"""
IDSV question selection + conversion (single-pass, CSV -> dropdown items).

Reads the idsv-old-exams question-bank CSV and converts each picked question
into a "unified dropdown" (gapselect) item, except Generative-AI questions which
stay as freetext essays. See the exam working folder's CLAUDE.md for the rules.

Item dicts (consumed by MoodleBackupBuilder):
    {"qtype": "gapselect", "name", "text", "options"[], "answer_index"(1-based),
     "generalfeedback", "points", "source_id"}
    {"qtype": "essay", "name", "text", "points", "source_id"}
"""
import csv
import random
import re

# Dropdown instruction shown under every converted question (matches old exam).
PICK_INSTRUCTION = (
    "<hr><p><em>Välj ditt svar med rullgardinsmenyn ovan! "
    "Pick your answer using the drop down menu above!</em></p>")

# Subjects whose answers are numeric/bit-pattern (-> generated numeric distractors).
NUMERIC_SUBJECTS = {"BIN", "HEX", "TWO", "COL", "HER", "FLO", "REG", "PRC", "INR"}


def load_rows(csv_path):
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _clean(s):
    return (s or "").strip()


def _norm_answer(a):
    """Normalise an answer for display/matching (drop trailing period/space)."""
    return _clean(a).rstrip(".").strip()


def combine(se, en):
    """Glossary form 'Svenska (English)', or the single available side."""
    se, en = _norm_answer(se), _norm_answer(en)
    if se and en and se.lower() != en.lower():
        return f"{se} ({en})"
    return se or en


def is_short_answer(row):
    a = _clean(row.get("ans_se")) or _clean(row.get("ans_en"))
    if not a:
        return False
    a = _norm_answer(a)
    return ("\n" not in a) and len(a) <= 60 and _clean(row.get("type")) != "matching"


def is_numeric(row):
    a = _norm_answer(_clean(row.get("ans_se")) or _clean(row.get("ans_en")))
    if re.fullmatch(r"[0-9A-Fa-f][0-9A-Fa-f ]*", a):
        return True
    return _clean(row.get("subject")) in NUMERIC_SUBJECTS


def bilingual_text(row):
    """SV paragraph + EN italic paragraph, matching the old exam rendering."""
    se = _clean(row.get("q_se"))
    en = _clean(row.get("q_en"))
    parts = []
    if se:
        parts.append(f"<p>{se}</p>")
    if en and en.lower() != se.lower():
        parts.append(f"<p><em>{en}</em></p>")
    return "\n".join(parts) if parts else "<p></p>"


# ---- numeric option spaces -----------------------------------------------

def numeric_options(answer):
    """For an answer that ranges over a small fixed space, return
    (all_options_sorted, shuffle=False) so the dropdown lists every possible
    value (e.g. a hex byte -> 00..FF). Returns None when the space is too big."""
    a = _norm_answer(answer).upper()
    if re.fullmatch(r"[0-9A-F]{2}", a):            # one hex byte
        return [f"{i:02X}" for i in range(256)], False
    if re.fullmatch(r"[01]{8}", a):                # one 8-bit binary pattern
        return [format(i, "08b") for i in range(256)], False
    return None


# ---- numeric distractor generation ---------------------------------------

def _numeric_distractors(answer, rng, n=6):
    """Plausible wrong values that share the answer's shape (bits/hex/decimal)."""
    a = _norm_answer(answer)
    out = []
    seen = {a}

    def add(v):
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    bits_only = bool(re.fullmatch(r"[01 ]+", a))
    hex_only = bool(re.fullmatch(r"[0-9A-Fa-f ]+", a))

    attempts = 0
    while len(out) < n and attempts < 200:
        attempts += 1
        chars = list(a)
        positions = [i for i, c in enumerate(chars) if c != " "]
        if not positions:
            break
        # flip 1-2 symbols
        for _ in range(rng.randint(1, 2)):
            i = rng.choice(positions)
            if bits_only:
                chars[i] = "1" if chars[i] == "0" else "0"
            elif hex_only:
                d = "0123456789ABCDEF"
                cur = chars[i].upper()
                chars[i] = rng.choice([x for x in d if x != cur])
            else:
                chars[i] = str(rng.randint(0, 9))
        add("".join(chars))
    return out[:n]


# ---- eligibility ---------------------------------------------------------
#
# A question only becomes a dropdown if its answer fits one of the two formats
# that actually WORK as a dropdown:
#   (a) a clean fixed-space number  -> full value dropdown (e.g. hex byte 00..FF)
#   (b) a glossary concept term     -> the shared massive concept dropdown
# Calculation word-problems, descriptive ("what characterises X"), list ("name
# three…") and multi-statement answers are NOT eligible and are skipped.

def _answer_raw(row):
    return _norm_answer(_clean(row.get("ans_se")) or _clean(row.get("ans_en")))


# Questions that reference an explicit option list ("which of the following …")
# can't be a glossary/value dropdown — they need their own alternatives.
_LIST_REF_RE = re.compile(r"av följande|of the following", re.I)
# Questions asking for a *decimal* result must not get a hex-byte dropdown.
_WHICH_DECIMAL_RE = re.compile(r"vilke[tn]\s+decimal|which\s+decimal", re.I)
# Open-ended "give an example" questions don't work as a single-answer dropdown.
_OPEN_RE = re.compile(r"ge (ett |några )?exempel|give an? example|give examples|"
                      r"nämn\b|name (an|one|a few)", re.I)


def _question_text(row):
    return _clean(row.get("q_se")) + " " + _clean(row.get("q_en"))


def is_eligible_dropdown(row, pool_lower):
    qt = _question_text(row)
    if _LIST_REF_RE.search(qt) or _OPEN_RE.search(qt):
        return False
    if numeric_options(_answer_raw(row)) is not None:
        return not _WHICH_DECIMAL_RE.search(qt)
    return combine(row.get("ans_se"), row.get("ans_en")).lower() in pool_lower


def correct_answer(row, pool_canon):
    """The canonical correct option for an eligible row (term or number)."""
    if numeric_options(_answer_raw(row)) is not None:
        return _answer_raw(row).upper()
    return pool_canon.get(combine(row.get("ans_se"), row.get("ans_en")).lower())


# ---- conversion ----------------------------------------------------------

def row_to_dropdown(row, glossary_pool, pool_canon, rng, points=1.0):
    """Convert an *eligible* CSV row into a gapselect (dropdown) item."""
    num = numeric_options(_answer_raw(row))
    if num is not None:
        options, shuffle = num            # full sorted value space, no shuffle
        correct = _answer_raw(row).upper()
    else:
        # glossary concept term: correct answer is a real pool entry
        correct = pool_canon[combine(row.get("ans_se"), row.get("ans_en")).lower()]
        options = list(glossary_pool)
        shuffle = True

    if shuffle:
        rng.shuffle(options)
    answer_index = options.index(correct) + 1  # 1-based, used as [[N]]

    name = f"Q{_clean(row.get('id'))} - {_clean(row.get('subject')) or 'IDSV'}"
    text = bilingual_text(row) + f"\n<p>[[{answer_index}]]</p>" + PICK_INSTRUCTION
    gf = f"<p><strong>Förväntat svar / Expected answer:</strong> {correct}</p>"
    return {
        "qtype": "gapselect",
        "name": name,
        "text": text,
        "options": options,
        "answer_index": answer_index,
        "shuffle": shuffle,
        "generalfeedback": gf,
        "points": points,
        "source_id": _clean(row.get("id")),
    }


def row_to_essay(row, points=1.0):
    name = f"Q{_clean(row.get('id'))} - {_clean(row.get('subject')) or 'IDSV'}"
    return {
        "qtype": "essay",
        "name": name,
        "text": bilingual_text(row),
        "points": points,
        "source_id": _clean(row.get("id")),
    }


# ---- selection -----------------------------------------------------------

def select_dropdowns(rows, chapter, count, rng, glossary_pool, points=1.0,
                     exclude_ids=(), exclude_answers=None):
    """Pick `count` dropdown-eligible rows from `chapter` and convert them.
    `exclude_answers` (a set) prevents the same correct answer recurring across
    the exam; picked answers are added to it."""
    pool_lower = {p.lower() for p in glossary_pool}
    pool_canon = {p.lower(): p for p in glossary_pool}
    seen = exclude_answers if exclude_answers is not None else set()
    candidates = [r for r in rows
                  if _clean(r.get("chapter")) == str(chapter)
                  and _clean(r.get("id")) not in exclude_ids
                  and is_eligible_dropdown(r, pool_lower)]
    rng.shuffle(candidates)
    picked = []
    for r in candidates:
        if len(picked) == count:
            break
        ans = correct_answer(r, pool_canon)
        if ans in seen:
            continue
        seen.add(ans)
        picked.append(row_to_dropdown(r, glossary_pool, pool_canon, rng, points))
    if len(picked) < count:
        raise SystemExit(
            f"Chapter {chapter}: only {len(picked)} distinct dropdown-eligible "
            f"questions after dedup, need {count}.")
    return picked


def shortanswer_from_id(rows, qid, accepted, rng=None, points=1.0,
                        instruction_sv="", instruction_en=""):
    """Build a text-box (shortanswer) item from a CSV question id.
    `accepted` = list of accepted answers (full marks; '*' wildcards allowed)."""
    row = next((r for r in rows if _clean(r.get("id")) == str(qid)), None)
    if row is None:
        raise SystemExit(f"Shortanswer id {qid} not found in CSV.")
    text = bilingual_text(row)
    instr = " ".join(x for x in (instruction_sv, instruction_en) if x).strip()
    if instr:
        text += f"<hr><p><em>{instr}</em></p>"
    correct = combine(row.get("ans_se"), row.get("ans_en"))
    return {
        "qtype": "shortanswer",
        "name": f"Q{_clean(row.get('id'))} - {_clean(row.get('subject')) or 'IDSV'}",
        "text": text,
        "accepted": list(accepted),
        "generalfeedback": (
            f"<p><strong>Förväntat svar / Expected answer:</strong> "
            f"{correct}</p>"),
        "points": points,
        "source_id": _clean(row.get("id")),
    }


def essays_by_ids(rows, ids, points=1.0):
    """Return essays for the given CSV question ids, in the listed order."""
    by_id = {_clean(r.get("id")): r for r in rows}
    out = []
    for qid in ids:
        r = by_id.get(str(qid))
        if r is None:
            raise SystemExit(f"Essay id {qid} not found in CSV.")
        out.append(row_to_essay(r, points))
    return out


def select_essays(rows, chapter, count, rng, points=1.0, subjects=None,
                  exclude_ids=(), min_answer_len=0):
    """Pick `count` freetext rows -> essays. `min_answer_len` filters out
    list/one-liner answers so we keep genuine writing questions (GenAI)."""
    pool = [r for r in rows
            if _clean(r.get("chapter")) == str(chapter)
            and not is_short_answer(r)
            and len(_clean(r.get("ans_se") or r.get("ans_en"))) >= min_answer_len
            and _clean(r.get("id")) not in exclude_ids]
    if subjects:
        pool = [r for r in pool if _clean(r.get("subject")) in subjects]
    if len(pool) < count:
        raise SystemExit(
            f"Chapter {chapter!r}: only {len(pool)} essay questions match "
            f"(min_answer_len={min_answer_len}), need {count}.")
    rng.shuffle(pool)
    return [row_to_essay(r, points) for r in pool[:count]]
