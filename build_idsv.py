#!/usr/bin/env python3
"""
Build the IDSV resit (uppsamling) exam .mbz.

Single-pass assembly:
  - questions picked from the idsv-old-exams CSV, converted to unified dropdowns
    (glossary pool from the old mbz for terms; full value-space for numbers),
  - Generative-AI questions kept as freetext essays,
  - machine-language section (ISA + config descriptions + R3/R1/PC dropdowns),
  - the new CodeRunner programming question lifted from the course-452 mbz.

Usage:
    python build_idsv.py --date 2026-08-20 --start 09:00 --end 13:00 \
        [--seed 570028735] [-o idsv_uppsamling.mbz] [--config courses/idsv.json]
"""
import argparse
import json
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import idsv_questions as iq
import idsv_machine as im
from mbz_extract import extract_question
from moodle_backup_builder import MoodleBackupBuilder

# Exam times are given in Stockholm local time (matches the iexam export).
EXAM_TZ = ZoneInfo("Europe/Stockholm")


def to_timestamp(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return int(dt.replace(tzinfo=EXAM_TZ).timestamp())


def build_sections(cfg, rng):
    rows = iq.load_rows(cfg["question_csv"])
    pool = json.load(open(cfg["pool"]))["options"]
    dp = cfg.get("dropdown_points", 1.0)
    ep = cfg.get("essay_points", 1.0)
    overrides = cfg.get("overrides", {})  # per-question patches, keyed by CSV id
    used = set()       # CSV ids already picked
    used_answers = set()  # correct answers already used (no concept/value repeats)
    sections = []

    for spec in cfg["plan"]:
        items = []

        if spec.get("machine"):
            mitems = im.build_machine_items(
                working_dir=cfg["machine_dir"],
                appendix_tex=f"{cfg['machine_dir']}/{cfg['machine_appendix']}",
                answer_key=f"{cfg['machine_dir']}/{cfg['machine_answer_key']}",
                questions_txt=f"{cfg['machine_dir']}/{cfg['machine_questions']}",
                isa_html_path=cfg["isa_html"], rng=rng, points=dp)
            items.extend(mitems)

        if spec.get("dropdowns"):
            picks = iq.select_dropdowns(
                rows, spec["chapter"], spec["dropdowns"], rng, pool,
                points=dp, exclude_ids=used, exclude_answers=used_answers,
                overrides=overrides)
            for d in picks:
                used.add(d["source_id"])
            items.extend(picks)

        for sa in spec.get("shortanswers", []):
            item = iq.shortanswer_from_id(
                rows, sa["id"], sa["accepted"], points=dp,
                instruction_sv=sa.get("instruction_sv", ""),
                instruction_en=sa.get("instruction_en", ""))
            used.add(item["source_id"])
            items.append(item)

        if spec.get("essay_ids"):
            picks = iq.essays_by_ids(rows, spec["essay_ids"], points=ep)
            for e in picks:
                used.add(e["source_id"])
            items.extend(picks)
        elif spec.get("essays"):
            essay_chapter = spec.get("essay_chapter", spec.get("chapter"))
            picks = iq.select_essays(
                rows, essay_chapter, spec["essays"], rng, points=ep,
                subjects=set(spec.get("essay_subjects", [])), exclude_ids=used,
                min_answer_len=spec.get("essay_min_answer_len", 0))
            for e in picks:
                used.add(e["source_id"])
            items.extend(picks)

        # Reference info blocks (raw-HTML assets) rendered as descriptions;
        # placed just before the coderunner so they share its page.
        for blk in spec.get("info_html", []):
            items.append({"qtype": "description", "name": blk["name"],
                          "text": Path(blk["html"]).read_text(encoding="utf-8")})

        if spec.get("coderunner"):
            items.append(extract_question(cfg["coderunner_mbz"], "coderunner"))

        sections.append({"name": spec["name"], "items": items})

    # Per-question overrides only take effect if that question was drawn; warn
    # loudly if any went unused (e.g. the seed changed and it wasn't picked).
    unused = set(overrides) - used
    if unused:
        raise SystemExit(
            f"Overrides for ids {sorted(unused)} were not applied — those "
            f"questions weren't selected (seed/selection changed?).")
    return sections


def main():
    p = argparse.ArgumentParser(description="Build the IDSV resit exam .mbz")
    p.add_argument("--config", default="courses/idsv.json")
    p.add_argument("--date", required=True, help="Exam date YYYY-MM-DD")
    p.add_argument("--start", required=True, help="Start time HH:MM")
    p.add_argument("--end", required=True, help="End time HH:MM")
    p.add_argument("--seed", type=int, default=570028735)
    p.add_argument("--output", "-o", default=None)
    args = p.parse_args()

    cfg = json.load(open(args.config))
    rng = random.Random(args.seed)

    time_open = to_timestamp(args.date, args.start)
    time_close = to_timestamp(args.date, args.end)

    sections = build_sections(cfg, rng)

    output = args.output or f"idsv_uppsamling_{args.date}.mbz"
    builder = MoodleBackupBuilder(
        title=cfg["title"], time_open=time_open, time_close=time_close,
        timelimit=time_close - time_open,
        mc_points=cfg.get("dropdown_points", 1.0),
        essay_points=cfg.get("essay_points", 1.0),
        sections=sections,
        contact_name=cfg.get("contact_name", "Edwin"),
        contact_email=cfg.get("contact_email", "edwinsu@dsv.su.se"),
        essays_last=False,
        grade_letters=[(l, p) for l, p in cfg["grade_letters"]] if cfg.get("grade_letters") else None,
        embed_grade_feedback=cfg.get("embed_grade_feedback", True),
        programming_min_points=cfg.get("programming_min_points"),
        answer_guidance=cfg.get("answer_guidance"))
    builder.build(output)

    # Report
    from collections import Counter
    qc = Counter(it["qtype"] for s in builder.sections for it in s["items"])
    print(f"Generated {output}")
    print(f"  Title:  {cfg['title']}")
    print(f"  Date:   {args.date} {args.start}-{args.end}")
    print(f"  Total:  {builder.total_points:.0f}p")
    print(f"  Items:  {dict(qc)}")
    for s in builder.sections:
        qs = Counter(it["qtype"] for it in s["items"])
        print(f"    {s['name'][:45]:45} {dict(qs)}")


if __name__ == "__main__":
    main()
