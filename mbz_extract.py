"""
Lift questions verbatim from an exported Moodle .mbz so they can be
re-embedded in a generated exam. The exact <plugin_qtype_*_question> block
(options, test cases, …) is reused untouched; the builder only re-wraps it
with fresh ids (see the generic verbatim path in MoodleBackupBuilder).
"""
import re
import tarfile
from xml.sax.saxutils import unescape


def _field(body, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.S)
    return m.group(1) if m else ""


def extract_question(mbz_path, qtype, name=None):
    """Return one question of `qtype` (optionally matched by `name`) as a
    builder item: {qtype, name, text, points, penalty, plugin_xml,
    generalfeedback, raw_text, raw_feedback}. Text and feedback stay
    export-escaped (the raw_* flags tell the builder not to re-escape).

    A full-course export keeps every version of a question, and NOT in
    version order in the file (the newest can come first), so the candidate
    with the latest <timemodified> is picked rather than the last in file
    order."""
    with tarfile.open(mbz_path, "r:gz") as tar:
        xml = tar.extractfile("questions.xml").read().decode("utf-8")

    blocks = [m.group(1) for m in re.finditer(
        r"<question id=\"\d+\">(.*?)</question>", xml, re.S)
        if f"<qtype>{qtype}</qtype>" in m.group(1)]
    if name is not None:
        blocks = [b for b in blocks if unescape(_field(b, "name")) == name]
    if not blocks:
        what = f"{qtype} question" + (f" named {name!r}" if name else "")
        raise SystemExit(f"No {what} found in {mbz_path}")

    def _timemodified(b):
        m = re.search(r"<timemodified>(\d+)</timemodified>", b)
        return int(m.group(1)) if m else -1

    body = max(blocks, key=_timemodified)

    plugin = re.search(
        rf"<plugin_qtype_{qtype}_question>.*?</plugin_qtype_{qtype}_question>",
        body, re.S)
    return {
        "qtype": qtype,
        "name": unescape(_field(body, "name")),
        "text": _field(body, "questiontext"),  # already escaped (raw export)
        "points": float(_field(body, "defaultmark")),
        "penalty": float(_field(body, "penalty") or 0.0),
        "plugin_xml": plugin.group(0) if plugin else "",
        "generalfeedback": _field(body, "generalfeedback"),
        "raw_text": True,        # tells the builder not to re-escape
        "raw_feedback": True,
    }
