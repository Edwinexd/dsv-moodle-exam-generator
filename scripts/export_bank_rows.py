#!/usr/bin/env python3
"""
Fold a held exam back into the idsv-old-exams question bank.

Once a sitting is over its questions become old-exam material: every question
that was examined gets a row in the bank CSV, tagged with the sitting it was
used in (`2026gA`, `2026gB`, …), exactly the way the 2025 exams are stored.
Questions that were *drawn from* the bank already have a row — those only get
the new tag (and a question number, if they had none).

Each exam is rebuilt from its config so the rows describe what the students
actually sat, and the built quiz supplies the question numbers as the student
saw them (Moodle numbers answerable slots and skips the info blocks).

What a row is made of, per question source:
  authored (`P<id>`)  the authored JSON spec + its `bank` key ({type, subject},
                      optionally `appendix` for a question with a figure)
  config item (`V<n>`) the item dict in the config + its `bank` key
  machine language    the group's questions/answer-key files in the working
                      folder; the appendix reference is rewritten to the name
                      the bank keeps it under (machine-<tag>.tex)
  CodeRunner          the question text out of the built backup
  bank question (`Q<id>`) nothing — the existing row just gains the tag

Usage:
    python scripts/export_bank_rows.py --date 2026-09-26 \\
        --exam courses/idsv_ht2026_g1.json 2026gA 08:00 11:00 \\
        --exam courses/idsv_ht2026_g2.json 2026gB 12:00 15:00 \\
        --exam courses/idsv_ht2026_g3.json 2026gC 16:00 19:00 \\
        [--csv ~/idsv-old-exams/question_bank/2025-08-31.csv] [--dry-run]

The machine-language appendices still have to be copied into the bank's
`appendixes/` as machine-<tag>.tex; the script prints which ones it expects.
"""
import argparse
import csv
import html
import io
import random
import re
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_idsv as B                                     # noqa: E402
import idsv_authored as ia                                 # noqa: E402
from moodle_backup_builder import MoodleBackupBuilder      # noqa: E402

FIELDS = ["id", "q#", "chapter", "type", "subject", "order",
          "q_se", "q_en", "ans_se", "ans_en",
          "q_alt_se", "q_alt_en", "ans_alt_se", "ans_alt_en", "tags"]

# Alternatives are joined with ';' — the bank's parser tries that separator
# first, and these option texts contain commas of their own.
ALT_SEP = "; "

# Paragraphs that are exam furniture rather than part of the question.
_NOISE_RE = re.compile(r"Vid oklarhet|In case of ambiguity|"
                       r"Välj ditt svar|Pick your answer", re.I)


# ---------------------------------------------------------------- bank CSV

def read_bank(path):
    """Rows as (fields, raw_text) so untouched rows can be written back
    byte for byte — the file is data, and a re-quoted line is noise."""
    with open(path, newline="", encoding="utf-8") as f:
        seen = []

        def feed():
            for line in f:
                seen.append(line)
                yield line

        for row in csv.reader(feed()):
            raw, seen[:] = "".join(seen), []
            yield row, raw


def serialize(row):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow(row)
    return buf.getvalue()


# ------------------------------------------------------------ html -> text

def paragraphs(text):
    """The question's own paragraphs, in order, as plain text."""
    text = re.split(r"<hr\s*/?>", text)[0]
    out = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", text, re.S):
        body = m.group(1)
        if "<img" in body or re.fullmatch(r"\s*\[\[\d+\]\]\s*", body):
            continue
        plain = html.unescape(re.sub(r"<[^>]+>", "", body)).strip()
        if plain and not _NOISE_RE.search(plain):
            out.append(plain)
    return out


def bilingual(text):
    """(Swedish, English) out of the question's SV + italic-EN paragraphs."""
    paras = paragraphs(text)
    if not paras:
        return "", ""
    if len(paras) == 1:
        return paras[0], ""
    return paras[0], paras[1]


def code_text(text):
    """A CodeRunner question: HTML blob -> the SV half and the EN half."""
    s = html.unescape(html.unescape(text))
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", s)).strip()
    # Both languages sit in one field, the English half opening with its own
    # copy of the standing instructions.
    parts = re.split(r"\n\s*\n(?=The program can be edited)", s, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (s, "")


# ------------------------------------------------------------- built quiz

def build_and_read(config, date, start, end):
    """Build the exam and read back (config, [(display_no, name, qtype, question)])."""
    cfg = B.load_config(config)
    rng = random.Random(cfg.get("seed", 570028735))
    sections = B.build_sections(cfg, rng)
    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp) / "exam.mbz")
        MoodleBackupBuilder(
            title=cfg.get("title_template", cfg["title"]).format(
                date=date, start=start, end=end),
            time_open=B.to_timestamp(date, start),
            time_close=B.to_timestamp(date, end),
            timelimit=cfg.get("timelimit", 0),
            mc_points=cfg.get("dropdown_points", 1.0),
            essay_points=cfg.get("essay_points", 1.0),
            sections=sections,
            essays_last=False,
            grade_letters=[(l, p) for l, p in cfg["grade_letters"]] if cfg.get("grade_letters") else None,
            embed_grade_feedback=cfg.get("embed_grade_feedback", True),
            programming_min_points=cfg.get("programming_min_points"),
            answer_guidance=cfg.get("answer_guidance"),
            comment_boxes=cfg.get("comment_boxes"),
            comment_intro=cfg.get("comment_intro")).build(out)

        tar = tarfile.open(out, "r:gz")
        questions = ET.fromstring(tar.extractfile("questions.xml").read())
        quiz = ET.fromstring(tar.extractfile(next(
            n for n in tar.getnames() if n.endswith("quiz.xml"))).read())

    by_entry = {e.get("id"): e.find(".//question")
                for e in questions.iter("question_bank_entry")}
    slots, number = [], 0
    for qi in quiz.iter("question_instance"):
        q = by_entry[qi.findtext(".//questionbankentryid")]
        qtype = q.findtext("qtype")
        if qtype == "description":          # info blocks are not numbered
            continue
        number += 1
        slots.append((number, q.findtext("name"), qtype, q))
    return cfg, slots


# ------------------------------------------------------------------ rows

def authored_row(spec, number):
    if "bank" not in spec:
        sys.exit(f"{spec['q_se'][:40]!r}: no `bank` metadata in the authored file.")
    bank = spec["bank"]
    q_se, q_en = spec["q_se"], spec.get("q_en", "")
    if bank.get("appendix"):
        q_se += f" (Se %appendix:{bank['appendix']}%)"
        if q_en:
            q_en += f" (See %appendix:{bank['appendix']}%)"

    kind = spec["kind"]
    alt_se = alt_en = ""
    if kind in ("value", "choice"):
        ans_se = ans_en = spec["answer"]
        if kind == "choice":
            others = ALT_SEP.join(o for o in spec["options"] if o != spec["answer"])
            alt_se = alt_en = others
    else:
        ans_se, ans_en = spec.get("ans_se", ""), spec.get("ans_en", "")

    return {"q#": number, "chapter": spec.get("chapter", ""),
            "type": bank["type"], "subject": bank["subject"],
            "q_se": q_se, "q_en": q_en, "ans_se": ans_se, "ans_en": ans_en,
            "ans_alt_se": alt_se, "ans_alt_en": alt_en}


def item_row(item, number):
    """A question written straight into the config (the Vetenskaplighet set)."""
    bank = item["bank"]
    q_se, q_en = bilingual(item["text"])
    right = [o["text"] for o in item["options"] if o["correct"]]
    wrong = [o["text"] for o in item["options"] if not o["correct"]]
    return {"q#": number, "chapter": "", "type": bank["type"],
            "subject": bank["subject"], "q_se": q_se, "q_en": q_en,
            "ans_se": ALT_SEP.join(right), "ans_en": ALT_SEP.join(right),
            "ans_alt_se": ALT_SEP.join(wrong), "ans_alt_en": ALT_SEP.join(wrong)}


def machine_rows(cfg, tag):
    """The group's machine-language questions, straight from the toolkit's own
    question and answer-key files, with the appendix renamed to the one the
    bank keeps (machine-<tag>.tex)."""
    d = Path(cfg["machine_dir"])
    asked = (d / cfg["machine_questions"]).read_text(encoding="utf-8")
    key = (d / cfg["machine_answer_key"]).read_text(encoding="utf-8")
    answers = dict(re.findall(r"^\s{2}(\w+):\s*([0-9A-F]+)\s*$", key, re.M))

    rows = {}
    for subject, target, en, se in re.findall(
            r"\[(\w+)\]\s+(\S+)\n\s*EN:\s*(.*)\n\s*SV:\s*(.*)", asked):
        fix = lambda s: re.sub(r"%appendix:[^%]+%", f"%appendix:machine-{tag}.tex%", s)
        rows[target] = {"chapter": 2, "type": "sa", "subject": subject,
                        "q_se": fix(se.strip()), "q_en": fix(en.strip()),
                        "ans_se": answers[target], "ans_en": answers[target]}
    return rows


def code_row(question, number):
    q_se, q_en = code_text(question.findtext("questiontext") or "")
    return {"q#": number, "chapter": "", "type": "code", "subject": "PRG",
            "q_se": q_se, "q_en": q_en, "ans_se": "", "ans_en": ""}


# ------------------------------------------------------------------ main

def collect(exams, date, csv_path):
    """Walk every sitting and return (tags to add to existing bank rows,
    new rows keyed by identity, in the order they were first examined)."""
    add_tags, new_rows = {}, {}

    for config, tag, start, end in exams:
        cfg, slots = build_and_read(config, date, start, end)
        authored = ia.load_authored(cfg["authored"]) if cfg.get("authored") else {}
        by_name = {i["name"]: i for s in cfg["plan"] for i in s.get("items", [])}
        machine = machine_rows(cfg, tag)

        for number, name, qtype, question in slots:
            if name.startswith("Kommentarer"):      # comment boxes
                continue

            bank_id = re.fullmatch(r"Q(\d+) - .*", name)
            authored_id = re.fullmatch(r"P(\S+) - .*", name)
            machine_q = re.fullmatch(r"Maskinspråk / Machine language - (\S+)", name)

            if bank_id:                              # already in the bank
                add_tags.setdefault(bank_id.group(1), []).append((tag, number))
                continue

            if authored_id:
                key, make = f"P{authored_id.group(1)}", lambda: authored_row(
                    authored[authored_id.group(1)], number)
            elif machine_q:                          # never shared between groups
                key, make = f"machine:{tag}:{machine_q.group(1)}", lambda: dict(
                    machine[machine_q.group(1)], **{"q#": number})
            elif qtype == "coderunner":
                key, make = f"code:{name}", lambda: code_row(question, number)
            elif name in by_name:
                key, make = f"item:{name}", lambda: item_row(by_name[name], number)
            else:
                sys.exit(f"Don't know where question {name!r} came from.")

            if key not in new_rows:
                new_rows[key] = {**make(), "tags": []}
            new_rows[key]["tags"].append(tag)

    return add_tags, new_rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", default="/Users/edwin/idsv-old-exams/question_bank/2025-08-31.csv")
    p.add_argument("--date", required=True, help="Exam date YYYY-MM-DD")
    p.add_argument("--exam", nargs=4, action="append", required=True,
                   metavar=("CONFIG", "TAG", "START", "END"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    add_tags, new_rows = collect(args.exam, args.date, args.csv)

    bank = list(read_bank(args.csv))
    header = bank[0][0]
    if header != FIELDS:
        sys.exit(f"Unexpected bank columns: {header}")
    next_id = max(int(r[0]) for r, _ in bank[1:] if r and r[0].isdigit()) + 1

    out, touched = [], []
    for row, raw in bank:
        qid = row[0] if row else ""
        if qid in add_tags:
            fields = dict(zip(FIELDS, row))
            tags = [t for t in fields["tags"].split(",") if t]
            for tag, number in add_tags[qid]:
                if tag not in tags:
                    tags.append(tag)
            fields["tags"] = ",".join(tags)
            if not fields["q#"]:
                fields["q#"] = str(add_tags[qid][0][1])
            out.append(serialize([fields[f] for f in FIELDS]))
            touched.append(f"  {qid:>4}  + {','.join(t for t, _ in add_tags[qid])}")
        else:
            out.append(raw)

    added = []
    for row in new_rows.values():
        row = {**{f: "" for f in FIELDS}, **row, "id": next_id,
               "tags": ",".join(row["tags"])}
        out.append(serialize([str(row[f]) for f in FIELDS]))
        added.append(f"  {next_id:>4}  q#{str(row['q#']):<3} ch{str(row['chapter']):<3} "
                     f"{row['type']:<6} {row['subject']:<4} {row['tags']:<22} "
                     f"{row['q_se'][:52]}")
        next_id += 1

    print(f"Tagged {len(touched)} existing question(s):")
    print("\n".join(touched))
    print(f"\nNew question(s) — {len(added)}:")
    print("\n".join(added))
    appendices = sorted({f"machine-{tag}.tex" for _, tag, _, _ in args.exam})
    print("\nAppendices the new rows refer to (copy into the bank's appendixes/):")
    print("  " + "\n  ".join(appendices))

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        f.write("".join(out))
    print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
