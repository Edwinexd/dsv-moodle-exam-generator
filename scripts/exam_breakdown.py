#!/usr/bin/env python3
"""
Print what a built exam actually contains, slot by slot: the quiz section, the
question, how the student answers it and what the key says. Meant for eyeballing
a finished .mbz before it goes live.

Usage: python scripts/exam_breakdown.py <exam.mbz> [more.mbz ...]
"""
import re
import sys
import tarfile
import xml.etree.ElementTree as ET
from html import unescape


def response_type(q):
    """How the student answers — the thing that isn't obvious from the qtype."""
    qtype = q.findtext("qtype")
    if qtype == "gapselect":
        opts = [a.findtext("answertext") for a in q.iter("answer")]
        n = len(opts)
        # a value space lists every hex byte / 8-bit pattern; anything else big
        # is the shared glossary
        if all(re.fullmatch(r"[0-9A-F]{2}", o or "") for o in opts):
            return f"dropdown (hex 00-FF)"
        if all(re.fullmatch(r"[01]{8}", o or "") for o in opts):
            return f"dropdown (8-bit, 256)"
        if n > 100:
            return f"dropdown (glossary {n})"
        return f"dropdown ({n} options)"
    if qtype == "multichoice":
        single = q.findtext(".//single")
        n = len(list(q.iter("answer")))
        return f"{'one of' if single == '1' else 'select all'} {n}"
    if qtype == "shortanswer":
        return f"text box ({len(list(q.iter('answer')))} accepted)"
    return {"essay": "free text", "description": "-",
            "coderunner": "code (Python)"}.get(qtype, qtype)


def answer_of(q):
    qtype = q.findtext("qtype")
    if qtype == "description":
        return ""
    if qtype == "essay":
        return "(manually marked)"
    if qtype == "coderunner":
        return "(auto-graded tests)"
    if qtype == "multichoice" and q.findtext(".//single") == "0":
        n = sum(1 for a in q.iter("answer") if float(a.findtext("fraction")) > 0)
        per = max(float(a.findtext("fraction")) for a in q.iter("answer"))
        return f"{n} correct, full mark at {round(1 / per)} ticks"
    gf = unescape(q.findtext("generalfeedback") or "")
    m = re.search(r"Expected answer:</strong>\s*(.*?)</p>", gf)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else "?"


def breakdown(path):
    t = tarfile.open(path, "r:gz")
    qroot = ET.fromstring(t.extractfile("questions.xml").read())
    quiz = ET.fromstring(t.extractfile(
        next(n for n in t.getnames() if n.endswith("quiz.xml"))).read())

    by_entry = {}
    for e in qroot.iter("question_bank_entry"):
        by_entry[e.get("id")] = e.find(".//question")
    heads = {h.findtext("firstslot"): h.findtext("heading")
             for h in quiz.iter("section")}

    print("=" * 100)
    print(path.rsplit("/", 1)[-1])
    print(f"{'#':>3}  {'question':<26} {'moodle type':<12} {'answered by':<21} "
          f"{'p':>3}  key")
    print("-" * 100)
    total = 0.0
    for qi in quiz.iter("question_instance"):
        slot = qi.findtext("slot")
        if slot in heads:
            print(f"     -- {heads[slot]}")
        q = by_entry[qi.findtext(".//questionbankentryid")]
        mark = float(qi.findtext("maxmark"))
        total += mark
        name = (q.findtext("name") or "")[:26]
        print(f"{slot:>3}  {name:<26} {q.findtext('qtype'):<12} "
              f"{response_type(q):<21} {mark:>3.0f}  {answer_of(q)[:28]}")
    print("-" * 100)
    print(f"{'':>3}  total {total:.0f} p")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        breakdown(p)
