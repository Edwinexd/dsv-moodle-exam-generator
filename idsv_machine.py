"""
Machine-language (Brookshear/Vole) integration for the IDSV resit exam.

Single-pass: reads the already-generated artifacts in the exam working folder
(machine appendix .tex, the question list, and the answer key) and produces:
  - a static ISA description ("The Machine's Language" op-code table, reused
    verbatim from the old exam: courses/idsv_machine_isa.html),
  - a config description (intro + memory table + register table, new values),
  - one numeric dropdown per asked register/PC value (hex answer + distractors).

Answers are NOT recomputed here; they come from the answer-key file (which the
machine/ toolkit produced for the chosen seed).
"""
import re
from pathlib import Path

from idsv_questions import numeric_options


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def parse_appendix(tex_path):
    """Return (memory: {addr:content}, registers: {name:value}) from the .tex."""
    tex = _read(tex_path)
    hexpair = re.compile(r"\b([0-9A-F]{2})\s*&\s*([0-9A-F]{2})\b")

    # Memory: rows of "addr & content" pairs inside the first tabular.
    memory = {}
    mem_block = tex.split("initiala", 1)[0]  # memory table precedes registers
    for addr, content in hexpair.findall(mem_block):
        memory[addr] = content

    # Registers: header row names + value row, in the second tabular.
    registers = {}
    m = re.search(r"Program Counter \(PC\)\}(.*?)\\hline(.*?)\\hline", tex, re.S)
    if m:
        names = re.findall(r"R\d|PC", m.group(1))
        names = ["PC"] + [n for n in names if n != "PC"]
        vals = re.findall(r"\b([0-9A-F]{2})\b", m.group(2))
        for n, v in zip(names, vals):
            registers[n] = v
    return memory, registers


def parse_answers(key_path):
    """Return {label: hex} from the answer-key file (e.g. {'R3':'80',...})."""
    out = {}
    for m in re.finditer(r"^\s*(R\d|PC):\s*([0-9A-F]{2})\s*$", _read(key_path), re.M):
        out[m.group(1)] = m.group(2)
    return out


def parse_questions(q_path):
    """Return [{'target','en','sv'}] from the question list file."""
    items, cur = [], None
    for line in _read(q_path).splitlines():
        m = re.match(r"\[(\w+)\]\s*(\S+)", line)
        if m:
            cur = {"subject": m.group(1), "target": m.group(2), "en": "", "sv": ""}
            items.append(cur)
        elif cur and line.strip().startswith("EN:"):
            cur["en"] = line.split("EN:", 1)[1].strip()
        elif cur and line.strip().startswith("SV:"):
            cur["sv"] = line.split("SV:", 1)[1].strip()
    return items


def _strip_appendix_ref(text):
    return re.sub(r"\s*\(S[eü]e?\s*%appendix:[^%]+%\)", "", text).strip()


def _html_table(headers_and_rows):
    """Build a simple bordered HTML table from a list of rows (lists of cells)."""
    out = ['<table border="1" cellspacing="0" cellpadding="3">', "<tbody>"]
    for row in headers_and_rows:
        out.append("<tr>" + "".join(f"<td><p>{c}</p></td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def config_description_html(memory, registers):
    intro = (
        "<p>Antag att vi har en dator med maskininstruktioner enligt ovan "
        "(The Machine's Language), och följande innehåll (content) på "
        "hexadecimal notation i aktuell del av primärminnet (main memory):</p>"
        "<p><em>Assume that we have a computer with machine instructions as above "
        "(The Machine's Language), and the following content in hexadecimal "
        "notation in the current part of the main memory:</em></p>")
    addrs = sorted(memory)
    mem_tbl = _html_table([
        ["Adress / Address"] + addrs,
        ["Innehåll / Content"] + [memory[a] for a in addrs],
    ])
    reg_intro = (
        "<p>De olika registren har initiala värden enligt följande tabell:</p>"
        "<p><em>The various registers have initial values according to the "
        "following table:</em></p>")
    reg_names = list(registers)
    reg_tbl = _html_table([
        [{"PC": "PC"}.get(n, n) for n in reg_names],
        [registers[n] for n in reg_names],
    ])
    return intro + "\n" + mem_tbl + "\n" + reg_intro + "\n" + reg_tbl


def build_machine_items(*, working_dir, appendix_tex, answer_key, questions_txt,
                        isa_html_path, rng, points=1.0):
    """Return the ordered list of machine-language items for chapter 2."""
    memory, registers = parse_appendix(appendix_tex)
    answers = parse_answers(answer_key)
    questions = parse_questions(questions_txt)

    items = []
    # 1. static ISA reference (reused verbatim)
    items.append({
        "qtype": "description",
        "name": "Maskinens språk / The Machine's Language",
        "text": Path(isa_html_path).read_text(encoding="utf-8"),
    })
    # 2. memory + register configuration for this exam
    items.append({
        "qtype": "description",
        "name": "Maskinkonfiguration / Machine configuration",
        "text": config_description_html(memory, registers),
    })
    # 3. one numeric dropdown per asked value
    for q in questions:
        ans = answers.get(q["target"])
        if not ans:
            continue
        # A register/PC value is one hex byte -> list every possible value 00..FF.
        options, _ = numeric_options(ans)
        idx = options.index(ans.upper()) + 1
        se = _strip_appendix_ref(q["sv"])
        en = _strip_appendix_ref(q["en"])
        text = f"<p>{se}</p>\n<p><em>{en}</em></p>\n<p>[[{idx}]]</p>"
        items.append({
            "qtype": "gapselect",
            "name": f"Maskinspråk / Machine language - {q['target']}",
            "text": text,
            "options": options,
            "answer_index": idx,
            "shuffle": False,
            "generalfeedback": (
                f"<p><strong>Förväntat svar / Expected answer:</strong> "
                f"{ans}</p>"),
            "points": points,
            "source_id": f"machine-{q['target']}",
        })
    return items
