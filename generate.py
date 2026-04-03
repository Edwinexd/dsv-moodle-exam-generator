#!/usr/bin/env python3
"""
Generate a Moodle .mbz exam backup from a course config and question pool.

Usage:
    python generate.py --config courses/pvt15.json \
        --date 2026-06-15 --start 08:00 --end 11:00

    python generate.py --config courses/idsv.json \
        --date 2026-08-20 --start 09:00 --end 12:00 \
        --seed 123 -o idsv_omtenta.mbz
"""
import argparse
import json
import random
from datetime import datetime, timezone

from moodle_backup_builder import MoodleBackupBuilder


def parse_args():
    p = argparse.ArgumentParser(description="Generate a Moodle .mbz exam backup")
    p.add_argument("--config", "-c", required=True,
                   help="Path to course config JSON")
    p.add_argument("--date", required=True, help="Exam date YYYY-MM-DD")
    p.add_argument("--start", required=True, help="Start time HH:MM")
    p.add_argument("--end", required=True, help="End time HH:MM")
    p.add_argument("--output", "-o", default=None,
                   help="Output .mbz filename (default: auto from config title)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for question selection (default: 42)")
    p.add_argument("--timelimit", type=int, default=None,
                   help="Quiz time limit in seconds (default: derived from start/end)")
    # Overrides (take precedence over config)
    p.add_argument("--title", default=None, help="Override exam title from config")
    p.add_argument("--mc-per-section", type=int, default=None,
                   help="Override MC questions per section")
    p.add_argument("--mc-points", type=float, default=None,
                   help="Override points per MC question")
    p.add_argument("--essay-points", type=float, default=None,
                   help="Override points per essay question")
    p.add_argument("--contact-name", default=None, help="Override contact name")
    p.add_argument("--contact-email", default=None, help="Override contact email")
    return p.parse_args()


def to_timestamp(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def select_questions(all_questions, distribution, count):
    """Select questions according to topic distribution, scaled to count."""
    total_weight = sum(distribution.values())
    scaled = {t: max(1, round(w / total_weight * count))
              for t, w in distribution.items()}
    diff = count - sum(scaled.values())
    topics_sorted = sorted(scaled.keys(),
                           key=lambda t: distribution[t], reverse=True)
    for t in topics_sorted:
        if diff == 0:
            break
        if diff > 0:
            scaled[t] += 1
            diff -= 1
        elif scaled[t] > 1:
            scaled[t] -= 1
            diff += 1

    selected = []
    for topic, n in scaled.items():
        pool = [q for q in all_questions if q.get("topic") == topic]
        random.shuffle(pool)
        singles = [q for q in pool if q["type"] == "single"]
        multis = [q for q in pool if q["type"] == "multi"]
        for i in range(n):
            if i % 2 == 0 and singles:
                selected.append(singles.pop())
            elif multis:
                selected.append(multis.pop())
            elif singles:
                selected.append(singles.pop())
    return selected


def main():
    args = parse_args()
    random.seed(args.seed)

    with open(args.config) as f:
        config = json.load(f)

    # Load question pool
    pool_path = config["question_pool"]
    with open(pool_path) as f:
        pool_data = json.load(f)
    all_questions = pool_data["questions"]

    # Resolve values (CLI overrides > config)
    title = args.title or config["title"]
    mc_points = args.mc_points if args.mc_points is not None else config.get("mc_points", 1.0)
    essay_points = args.essay_points if args.essay_points is not None else config.get("essay_points", 7.0)
    mc_per_section = args.mc_per_section if args.mc_per_section is not None else config.get("mc_per_section", 18)
    contact_name = args.contact_name or config.get("contact_name", "Edwin")
    contact_email = args.contact_email or config.get("contact_email", "edwinsu@dsv.su.se")

    time_open = to_timestamp(args.date, args.start)
    time_close = to_timestamp(args.date, args.end)
    timelimit = args.timelimit or (time_close - time_open)

    # Build sections from config
    sections = []
    for sec_cfg in config["sections"]:
        if "question_ids" in sec_cfg:
            # Manual selection by index into question pool
            mc_questions = [all_questions[i] for i in sec_cfg["question_ids"]]
        else:
            mc_questions = select_questions(
                all_questions, sec_cfg["distribution"], mc_per_section)

        essay = None
        if "essay" in sec_cfg:
            essay = {
                "name": sec_cfg["essay"]["name"],
                "text": sec_cfg["essay"]["text"],
            }

        sections.append({
            "name": sec_cfg["name"],
            "mc_questions": mc_questions,
            "essay": essay,
            "min_points": sec_cfg.get("min_points"),
        })

    output = args.output
    if not output:
        safe_title = title.lower().replace(" ", "_")
        output = f"{safe_title}_{args.date}.mbz"

    builder = MoodleBackupBuilder(
        title=title,
        time_open=time_open,
        time_close=time_close,
        timelimit=timelimit,
        mc_points=mc_points,
        essay_points=essay_points,
        sections=sections,
        contact_name=contact_name,
        contact_email=contact_email,
    )
    builder.build(output)

    total_mc = sum(len(s["mc_questions"]) for s in sections)
    total_essays = sum(1 for s in sections if s.get("essay"))
    total_points = builder.total_points

    print(f"Generated {output}")
    print(f"  Title:      {title}")
    print(f"  Date:       {args.date} {args.start}-{args.end}")
    print(f"  Time limit: {timelimit // 60} minutes")
    for s in sections:
        mc = len(s["mc_questions"])
        essay_str = f" + 1 essay ({essay_points:.0f}p)" if s.get("essay") else ""
        print(f"  {s['name']}: {mc} MC{essay_str}")
    print(f"  Total:      {total_points:.0f}p ({total_mc} MC x {mc_points:.0f}p + {total_essays} essays x {essay_points:.0f}p)")
    print(f"  Grade boundaries (Bologna):")
    from moodle_backup_builder import GRADE_LETTERS
    for pct, letter in GRADE_LETTERS:
        print(f"    {letter}: >= {pct:.0f}% ({total_points * pct / 100:.0f}/{total_points:.0f}p)")


if __name__ == "__main__":
    main()
