"""
Authored IDSV questions — the ones written for this exam rather than drawn from
the idsv-old-exams CSV (HT2026: Peter's set in `courses/idsv_ht2026_authored.json`).

Each spec is converted with the same house rules as the CSV path
(`idsv_questions`), so an authored question is indistinguishable from a drawn
one in the finished quiz:

    term   -> massive glossary dropdown over the whole shared pool, sorted by
              the English term, shuffle off. `pool_answer` names the exact
              glossary entry; it is appended to the pool when it is new.
    value  -> dropdown listing the full value space (8-bit binary / hex byte).
    choice -> dropdown over the question's own small option list, order kept.
    short  -> text box with a list of accepted answers.
    essay  -> free text.

A spec may carry `image` (a path); the question text then references it as
@@PLUGINFILE@@/<filename> and the builder stores the file in the backup.
"""
import json
from pathlib import Path

from idsv_questions import (PICK_INSTRUCTION, english_sort_key, numeric_options)


def load_authored(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _bilingual(spec):
    """SV paragraph + EN italic paragraph, matching the drawn questions."""
    parts = [f"<p>{spec['q_se']}</p>"]
    if spec.get("q_en") and spec["q_en"].lower() != spec["q_se"].lower():
        parts.append(f"<p><em>{spec['q_en']}</em></p>")
    if spec.get("image"):
        # The source files are far wider than a Moodle question column (the
        # gate figure is 1842 px), so the image has to scale down rather than
        # run off the side: img-fluid for the Boost theme, the inline style as
        # the fallback for any theme that doesn't define it.
        parts.append(
            f'<p><img src="@@PLUGINFILE@@/{Path(spec["image"]).name}" alt="" '
            f'class="img-fluid" '
            f'style="max-width: 100%; height: auto;" /></p>')
    return "\n".join(parts)


def _expected(text):
    return f"<p><strong>Förväntat svar / Expected answer:</strong> {text}</p>"


def _answer_text(spec):
    """The answer as shown in the general feedback (teacher-facing)."""
    se, en = spec.get("ans_se", ""), spec.get("ans_en", "")
    if se and en and se.lower() != en.lower():
        return f"{se} ({en})"
    return se or en or spec.get("answer", "")


def build_item(qid, spec, glossary_pool, points=1.0):
    """Convert one authored spec into a builder item."""
    kind = spec["kind"]
    name = f"P{qid} - {kind.upper()}"
    body = _bilingual(spec)
    item = {"name": name, "points": points, "source_id": f"authored-{qid}"}
    if spec.get("image"):
        item["image"] = spec["image"]

    if kind == "essay":
        # A short factual answer, not a real essay: a few lines of plain text,
        # matching the exam's "korta och koncisa" instruction.
        item.update({"qtype": "essay", "text": body,
                     "response_format": "plain",
                     "lines": spec.get("lines", 3)})
        return item

    if kind == "short":
        text = body
        instr = " ".join(x for x in (spec.get("instruction_se", ""),
                                     spec.get("instruction_en", "")) if x).strip()
        if instr:
            text += f"<hr><p><em>{instr}</em></p>"
        item.update({"qtype": "shortanswer", "text": text,
                     "accepted": list(spec["accepted"]),
                     "generalfeedback": _expected(_answer_text(spec))})
        return item

    # --- the three dropdown flavours ---------------------------------------
    if kind == "term":
        # The glossary entry IS the answer, so the feedback must quote it
        # verbatim — the author's own wording may differ from the pool's.
        correct = spec["pool_answer"]
        options = sorted(set(glossary_pool) | {correct}, key=english_sort_key)
        shuffle = False
        spec = {**spec, "ans_se": correct, "ans_en": ""}
    elif kind == "value":
        correct = spec["answer"].upper()
        space = numeric_options(correct)
        if space is None:
            raise SystemExit(f"{qid}: {correct!r} is not a fixed value space.")
        options, shuffle = space
    elif kind == "choice":
        correct = spec["answer"]
        options = list(spec["options"])          # author's order, kept
        if correct not in options:
            raise SystemExit(f"{qid}: answer {correct!r} is not among its options.")
        shuffle = False
    else:
        raise SystemExit(f"{qid}: unknown kind {kind!r}")

    answer_index = options.index(correct) + 1
    item.update({
        "qtype": "gapselect",
        "text": f"{body}\n<p>[[{answer_index}]]</p>" + PICK_INSTRUCTION,
        "options": options,
        "answer_index": answer_index,
        "shuffle": shuffle,
        "generalfeedback": _expected(_answer_text(spec) or correct),
    })
    return item


def build_items(qids, authored, glossary_pool, points=1.0):
    """Convert the listed authored question ids, in the listed order."""
    out = []
    for qid in qids:
        spec = authored.get(str(qid))
        if spec is None:
            raise SystemExit(f"Authored question {qid!r} not found.")
        out.append(build_item(str(qid), spec, glossary_pool, points))
    return out


def pool_additions(authored):
    """Glossary entries an authored `term` answer adds to the shared pool."""
    return [q["pool_answer"] for q in authored.values()
            if q["kind"] == "term" and "pool_answer" in q]
