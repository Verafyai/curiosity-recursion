"""Build the hashed 8-gram index of the dossier author's own assembled text for the content guard.

Usage: python eval/exclusion/build_ngrams.py OUT.txt FILE_OR_DIR [...]
HTML and text files are read; <blockquote>, <q>, scripts, styles, the references section and any
double-quoted passage of 40+ characters are removed first, so that quoted primary sources stay
findable and only the author's own prose is fingerprinted. Output is one hex hash per line and
contains no readable dossier text.
"""
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cr.sources.exclusion import grams  # noqa: E402


def prose(raw: str, is_html: bool) -> str:
    if is_html:
        raw = re.sub(r"(?is)<(script|style|blockquote|q|nav|footer)\b.*?</\1>", " ", raw)
        raw = re.sub(r"(?is)<h[1-6][^>]*>\s*(references|sources|notes and sources)\s*</h[1-6]>.*", " ", raw)
        raw = html.unescape(re.sub(r"(?is)</(p|div|li|h[1-6]|tr|br)>|<br\s*/?>", "\n", raw))
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = re.split(r"(?im)^\s*(references|sources|notes and sources)\s*$", raw)[0]
    raw = re.sub(r"\u201c[^\u201d\n]{40,800}\u201d", " ", raw)
    raw = re.sub(r"\"[^\"\n]{40,800}\"", " ", raw)
    return raw


out, paths = sys.argv[1], sys.argv[2:]
hs, nfiles = set(), 0
for p in paths:
    for f in ([Path(p)] if Path(p).is_file() else sorted(Path(p).rglob("*"))):
        if f.suffix.lower() in (".html", ".htm", ".txt", ".md"):
            hs.update(grams(prose(f.read_text(errors="ignore"), f.suffix.lower() in (".html", ".htm"))))
            nfiles += 1
Path(out).write_text("\n".join(f"{h:016x}" for h in sorted(hs)) + "\n")
print(f"{nfiles} files, {len(hs)} distinct 8-gram hashes -> {out}")
