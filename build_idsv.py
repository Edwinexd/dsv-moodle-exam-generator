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
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import idsv_questions as iq
import idsv_machine as im
import idsv_authored as ia
from mbz_extract import extract_question
from moodle_backup_builder import MoodleBackupBuilder

# Exam times are given in Stockholm local time (matches the iexam export).
EXAM_TZ = ZoneInfo("Europe/Stockholm")


def load_config(path):
    """Load a config, merging it onto the one named by `extends` (a path
    relative to the config itself). One key = one override; the three exam
    groups share a base and differ only in seed, machine artifacts and the
    CodeRunner export."""
    path = Path(path)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    base_name = cfg.pop("extends", None)
    if base_name is None:
        return cfg
    base = load_config(path.parent / base_name)
    base.update(cfg)
    return base


def to_timestamp(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return int(dt.replace(tzinfo=EXAM_TZ).timestamp())


def apply_text_rewrites(items, rewrites):
    """Apply the exam's wording rules to questions drawn from the CSV bank, so
    they read like the ones authored for this exam (HT2026: "kallas" ->
    "heter"). Authored and machine items are already written that way."""
    if not rewrites:
        return items
    for item in items:
        if not str(item.get("source_id", "")).isdigit():
            continue
        for pattern, repl in rewrites:
            item["text"] = re.sub(pattern, repl, item["text"])
    return items


def build_sections(cfg, rng):
    rows = iq.load_rows(cfg["question_csv"])
    pool = json.load(open(cfg["pool"]))["options"]

    # Authored questions (written for this exam, not drawn from the CSV). Their
    # glossary answers extend the shared pool ONCE, before anything is built, so
    # every dropdown in the exam shows the same menu.
    authored = ia.load_authored(cfg["authored"]) if cfg.get("authored") else {}
    for extra in ia.pool_additions(authored):
        if extra not in pool:
            pool.append(extra)
    dp = cfg.get("dropdown_points", 1.0)
    ep = cfg.get("essay_points", 1.0)
    overrides = cfg.get("overrides", {})  # per-question patches, keyed by CSV id
    used = set()       # CSV ids already picked
    used_answers = set()  # correct answers already used (no concept/value repeats)
    sections = []

    # Per-chapter content for this group: which authored questions it gets,
    # plus any bank fillers needed to reach the chapter's count.
    chapters = cfg.get("chapters", {})
    rewrites = cfg.get("text_rewrites", [])

    for spec in cfg["plan"]:
        spec = {**spec, **chapters.get(str(spec.get("chapter")), {})}
        items = []

        if spec.get("machine"):
            mitems = im.build_machine_items(
                working_dir=cfg["machine_dir"],
                appendix_tex=f"{cfg['machine_dir']}/{cfg['machine_appendix']}",
                answer_key=f"{cfg['machine_dir']}/{cfg['machine_answer_key']}",
                questions_txt=f"{cfg['machine_dir']}/{cfg['machine_questions']}",
                isa_html_path=cfg["isa_html"], rng=rng, points=dp)
            items.extend(mitems)

        # Questions authored for this exam; their answers are reserved so a
        # bank filler in the same chapter can't repeat the concept.
        for item in ia.build_items(spec.get("authored", []), authored, pool, dp):
            used.add(item["source_id"])
            if item.get("answer_index"):
                used_answers.add(item["options"][item["answer_index"] - 1])
            items.append(item)

        # Bank questions this group must not draw (a filler that clashed with
        # an authored question, or whose wording we don't want to patch).
        for qid in spec.get("exclude_ids", []):
            used.add(str(qid))

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

        # Questions written straight into the config (not drawn from the
        # CSV pool) — item dicts in builder form, used as-is.
        for item in spec.get("items", []):
            item.setdefault("points", dp)
            items.append(item)

        # Reference info blocks (raw-HTML assets) rendered as descriptions;
        # placed just before the coderunner so they share its page.
        for blk in spec.get("info_html", []):
            items.append({"qtype": "description", "name": blk["name"],
                          "text": Path(blk["html"]).read_text(encoding="utf-8")})

        if spec.get("coderunner"):
            items.append(extract_question(cfg["coderunner_mbz"], "coderunner",
                                          name=cfg.get("coderunner_name")))

        sections.append({"name": spec["name"],
                         "items": apply_text_rewrites(items, rewrites)})

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
    p.add_argument("--seed", type=int, default=None,
                   help="RNG seed; defaults to the config's `seed`")
    p.add_argument("--output", "-o", default=None)
    args = p.parse_args()

    cfg = load_config(args.config)
    seed = args.seed if args.seed is not None else cfg.get("seed", 570028735)
    rng = random.Random(seed)

    time_open = to_timestamp(args.date, args.start)
    time_close = to_timestamp(args.date, args.end)

    # Title: a template naming the sitting, else the plain configured title.
    title = cfg.get("title_template", cfg["title"]).format(
        date=args.date, start=args.start, end=args.end)
    # Time limit: the exam window by default; `"timelimit": 0` in the config
    # means no per-attempt limit at all, only the open/close times.
    timelimit = cfg["timelimit"] if "timelimit" in cfg else time_close - time_open

    sections = build_sections(cfg, rng)

    output = args.output or f"idsv_uppsamling_{args.date}.mbz"
    builder = MoodleBackupBuilder(
        title=title, time_open=time_open, time_close=time_close,
        timelimit=timelimit,
        mc_points=cfg.get("dropdown_points", 1.0),
        essay_points=cfg.get("essay_points", 1.0),
        sections=sections,
        contact_name=cfg.get("contact_name", "Edwin"),
        contact_email=cfg.get("contact_email", "edwinsu@dsv.su.se"),
        essays_last=False,
        grade_letters=[(l, p) for l, p in cfg["grade_letters"]] if cfg.get("grade_letters") else None,
        embed_grade_feedback=cfg.get("embed_grade_feedback", True),
        programming_min_points=cfg.get("programming_min_points"),
        answer_guidance=cfg.get("answer_guidance"),
        comment_boxes=cfg.get("comment_boxes"),
        comment_intro=cfg.get("comment_intro"))
    builder.build(output)

    # Report
    from collections import Counter
    qc = Counter(it["qtype"] for s in builder.sections for it in s["items"])
    print(f"Generated {output}")
    print(f"  Title:  {title}")
    print(f"  Date:   {args.date} {args.start}-{args.end}  (seed {seed})")
    print(f"  Limit:  {'none (open/close only)' if not timelimit else str(timelimit // 60) + ' min'}")
    print(f"  Total:  {builder.total_points:.0f}p")
    print(f"  Items:  {dict(qc)}")
    for s in builder.sections:
        qs = Counter(it["qtype"] for it in s["items"])
        print(f"    {s['name'][:45]:45} {dict(qs)}")


if __name__ == "__main__":
    main()
