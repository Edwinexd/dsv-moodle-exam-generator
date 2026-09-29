#!/usr/bin/env python3
"""
Offline validation of a generated exam .mbz (there is no live Moodle here).

Parses every XML in the archive and checks the invariants that actually break a
restore or a question:
  - every XML file parses,
  - each gapselect has exactly one [[N]] marker, in range, pointing at the
    option the general feedback names as the expected answer,
  - question ids are unique and every quiz slot resolves to a bank entry,
  - each image has a file record, a blob at files/<hash[:2]>/<hash> with a
    matching sha1 and size, and is referenced by its question's text,
  - the slot marks add up to the quiz's sumgrades.

Usage: python scripts/validate_mbz.py <exam.mbz> [more.mbz ...]
"""
import hashlib
import re
import sys
import tarfile
import xml.etree.ElementTree as ET
from html import unescape


def validate(path):
    t = tarfile.open(path, "r:gz")
    problems = []
    xmls = {}
    for m in t.getmembers():
        if m.name.endswith(".xml"):
            data = t.extractfile(m).read()
            xmls[m.name] = data
            try:
                ET.fromstring(data)
            except ET.ParseError as e:
                problems.append(f"{m.name} does not parse: {e}")

    qroot = ET.fromstring(xmls["questions.xml"])
    quiz = ET.fromstring(next(v for k, v in xmls.items() if k.endswith("quiz.xml")))

    # -- dropdowns: one [[N]], in range, matching the stated expected answer --
    gap_n = 0
    for q in qroot.iter("question"):
        name = q.findtext("name")
        if q.findtext("qtype") != "gapselect":
            continue
        gap_n += 1
        opts = [a.findtext("answertext") for a in q.iter("answer")]
        marks = re.findall(r"\[\[(\d+)\]\]", unescape(q.findtext("questiontext") or ""))
        if len(marks) != 1:
            problems.append(f"{name}: {len(marks)} [[N]] markers")
            continue
        n = int(marks[0])
        if not 1 <= n <= len(opts):
            problems.append(f"{name}: [[{n}]] out of range (1..{len(opts)})")
            continue
        gf = unescape(q.findtext("generalfeedback") or "")
        exp = re.search(r"Expected answer:</strong>\s*(.*?)</p>", gf)
        if exp:
            want = re.sub(r"<[^>]+>", "", exp.group(1)).strip()
            if want != opts[n - 1]:
                problems.append(
                    f"{name}: [[{n}]] -> {opts[n - 1]!r} but feedback says {want!r}")

    # -- select-all-that-apply: symmetric fractions, threshold reachable -----
    for q in qroot.iter("question"):
        mc = q.find(".//multichoice")
        if mc is None or mc.findtext("single") != "0":
            continue
        name = q.findtext("name")
        fracs = [float(a.findtext("fraction")) for a in q.iter("answer")]
        pos = [f for f in fracs if f > 0]
        neg = [f for f in fracs if f < 0]
        if not pos:
            problems.append(f"{name}: no correct option")
        if any(f == 0 for f in fracs):
            problems.append(f"{name}: an option scores 0 (neither right nor wrong)")
        if pos and neg and abs(pos[0] + neg[0]) > 1e-6:
            problems.append(f"{name}: a wrong tick ({neg[0]}) does not cancel a "
                            f"right one ({pos[0]})")
        if pos and sum(pos) < 1 - 1e-6:
            problems.append(f"{name}: all correct options together only reach "
                            f"{sum(pos):.2f} of the mark")

    # -- ids unique, slots resolve -------------------------------------------
    ids = [q.get("id") for q in qroot.iter("question")]
    if len(ids) != len(set(ids)):
        problems.append("duplicate question ids")
    bank = {e.get("id") for e in qroot.iter("question_bank_entry")}
    # the bank entry id sits inside <question_reference>, not on the instance
    slots = [qi.findtext(".//questionbankentryid")
             for qi in quiz.iter("question_instance")]
    missing = [s for s in slots if s not in bank]
    if missing:
        problems.append(f"{len(missing)}/{len(slots)} quiz slots resolve to no "
                        f"bank entry (e.g. {missing[0]!r})")

    # -- images ---------------------------------------------------------------
    fx = ET.fromstring(xmls["files.xml"])
    blobs = {n.rsplit("/", 1)[-1] for n in t.getnames() if n.startswith("files/")}
    imgs = [f for f in fx.iter("file") if f.findtext("filename") != "."]
    for f in imgs:
        h, fn, itemid = (f.findtext("contenthash"), f.findtext("filename"),
                         f.findtext("itemid"))
        if h not in blobs:
            problems.append(f"{fn}: no blob in the archive")
        else:
            data = t.extractfile(f"files/{h[:2]}/{h}").read()
            if hashlib.sha1(data).hexdigest() != h:
                problems.append(f"{fn}: contenthash does not match the blob")
            if int(f.findtext("filesize")) != len(data):
                problems.append(f"{fn}: filesize does not match the blob")
        q = next((q for q in qroot.iter("question") if q.get("id") == itemid), None)
        if q is None:
            problems.append(f"{fn}: itemid {itemid} is not a question")
        elif f"@@PLUGINFILE@@/{fn}" not in unescape(q.findtext("questiontext") or ""):
            problems.append(f"{fn}: question {itemid} does not reference it")

    # -- points ---------------------------------------------------------------
    total = sum(float(qi.findtext("maxmark")) for qi in quiz.iter("question_instance"))
    sumgrades = float(quiz.find(".//sumgrades").text)
    if abs(total - sumgrades) > 0.001:
        problems.append(f"slot marks {total} != sumgrades {sumgrades}")

    print(f"[{'OK ' if not problems else 'FAIL'}] {path}")
    print(f"        {len(xmls)} xml files, {len(ids)} questions ({gap_n} dropdowns), "
          f"{len(slots)} slots, {len(imgs)} images, {total:.0f}p")
    for p in problems:
        print(f"        - {p}")
    return not problems


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(0 if all([validate(p) for p in sys.argv[1:]]) else 1)
