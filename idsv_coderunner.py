"""
Extract the new CodeRunner programming question from an exported .mbz so it can
be re-embedded in the resit exam. We reuse the exact <plugin_qtype_coderunner_*>
block (options + test cases) verbatim and only re-wrap it with fresh ids.
"""
import re
import tarfile
from pathlib import Path


def prog_info_items(lists_html_path, strings_html_path):
    """Return the two Python-reference description blocks (list + string
    operations) that precede the CodeRunner question, mirroring the old exam.
    Stored as raw-HTML assets; the builder escapes them like any description."""
    return [
        {"qtype": "description", "name": "Operationer på listor",
         "text": Path(lists_html_path).read_text(encoding="utf-8")},
        {"qtype": "description", "name": "Operationer på strängar",
         "text": Path(strings_html_path).read_text(encoding="utf-8")},
    ]


def extract_coderunner(mbz_path):
    """Return {name, text(raw escaped), points, plugin_xml} for the latest
    CodeRunner question version in the .mbz."""
    with tarfile.open(mbz_path, "r:gz") as tar:
        xml = tar.extractfile("questions.xml").read().decode("utf-8")

    # Each <question ...> that is a coderunner; take the last (latest version).
    blocks = [m for m in re.finditer(
        r"<question id=\"\d+\">(.*?)</question>", xml, re.S)
        if "<qtype>coderunner</qtype>" in m.group(1)]
    if not blocks:
        raise SystemExit("No coderunner question found in " + mbz_path)
    body = blocks[-1].group(1)

    name = re.search(r"<name>(.*?)</name>", body, re.S).group(1)
    text = re.search(r"<questiontext>(.*?)</questiontext>", body, re.S).group(1)
    mark = re.search(r"<defaultmark>([\d.]+)</defaultmark>", body).group(1)
    plugin = re.search(
        r"<plugin_qtype_coderunner_question>.*?</plugin_qtype_coderunner_question>",
        body, re.S).group(0)

    return {
        "qtype": "coderunner",
        "name": name,
        "text": text,            # already HTML-escaped (raw from export)
        "points": float(mark),
        "plugin_xml": plugin,
        "raw_text": True,        # tells the builder not to re-escape
    }
