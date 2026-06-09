#!/usr/bin/env python3
"""
Extract the shared "massive dropdown" option pool (the SV (EN) glossary) from an
exported IDSV exam .mbz and save it as a JSON option list.

All large gapselect questions in the old exam share one identical ~301-entry
option pool; we lift it verbatim so unified-dropdown questions reuse the same
distractor set. See CLAUDE.md in the exam working folder.

Usage:
    python scripts/extract_pool.py OLD_EXAM.mbz -o courses/idsv_pool.json
"""
import argparse
import html
import json
import re
import tarfile
from pathlib import Path


def read_questions_xml(mbz_path):
    with tarfile.open(mbz_path, "r:gz") as tar:
        member = tar.getmember("questions.xml")
        return tar.extractfile(member).read().decode("utf-8")


def extract_pool(questions_xml):
    """Return the option list of the largest shared gapselect pool."""
    blocks = re.findall(
        r"<question id=\"\d+\">.*?</plugin_qtype_gapselect_question>",
        questions_xml, re.S)
    pools = []
    for block in blocks:
        options = re.findall(r"<answertext>(.*?)</answertext>", block, re.S)
        pools.append([html.unescape(o).strip() for o in options])
    if not pools:
        raise SystemExit("No gapselect questions found in mbz.")
    # The shared glossary is the pool whose option-set recurs most often
    # (301 entries, used by ~64 questions in HT2025) — not the largest one-off.
    from collections import Counter
    counts = Counter(tuple(p) for p in pools)
    shared, identical = counts.most_common(1)[0]
    return list(shared), len(pools), identical


def main():
    p = argparse.ArgumentParser(description="Extract dropdown option pool from an .mbz")
    p.add_argument("mbz", help="Path to the exported old exam .mbz")
    p.add_argument("-o", "--output", default="courses/idsv_pool.json",
                   help="Output JSON path (default: courses/idsv_pool.json)")
    args = p.parse_args()

    questions_xml = read_questions_xml(args.mbz)
    options, total_gapselect, identical = extract_pool(questions_xml)

    out = {
        "source": Path(args.mbz).name,
        "description": "Shared SV (EN) glossary option pool for unified dropdowns.",
        "options": options,
    }
    Path(args.output).write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"  options:          {len(options)}")
    print(f"  gapselect found:  {total_gapselect}")
    print(f"  share this pool:  {identical}")


if __name__ == "__main__":
    main()
