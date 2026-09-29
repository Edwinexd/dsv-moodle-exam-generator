#!/usr/bin/env python3
"""Generate the per-group machine artifacts (.tex + questions + answer key)."""
import subprocess, sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1
           else Path.home() / "Downloads" / "iexam-dsv-2026-09-26")
TOOLKIT = Path.home() / "idsv-old-exams"

for i in (1, 2, 3):
    seed = 9260000 + i
    tag = f"2026-09-26-g{i}"
    tex = OUT / f"machine-{tag}.tex"
    rep = subprocess.run(
        [sys.executable, "-m", "machine", "generate", "--seed", str(seed),
         "--cycles", "3", "--name", tag, "--out", str(tex)],
        cwd=TOOLKIT, capture_output=True, text=True, check=True).stdout

    # Split the report: student-facing questions / teacher-facing answer key.
    qs = rep.split("Questions (student-facing)", 1)[1]
    qs = qs.split("Answer key (teacher-facing)", 1)[0]
    qs = qs.strip().lstrip("=").strip()
    key = rep.split("Answer key (teacher-facing)", 1)[1].strip().lstrip("=").strip()

    (OUT / f"{tag}-questions.txt").write_text(
        f"Machine-language exam questions  (3 machine cycles)\n"
        f"Refers to appendix: machine-{tag}.tex\n\n{qs}\n", encoding="utf-8")
    (OUT / f"{tag}-ANSWER-KEY.txt").write_text(
        f"seed={seed}  (regenerate with: python -m machine generate "
        f"--seed {seed} --cycles 3 --name {tag})\n\n{key}\n", encoding="utf-8")
    print(f"group {i}: seed={seed} -> {tex.name}, {tag}-questions.txt, {tag}-ANSWER-KEY.txt")
