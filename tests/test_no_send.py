"""Outreach is ask-first and never sent: no code path can send mail or messages."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"\b(smtplib|sendmail|send_message|SMTP|postmark|sendgrid|mailgun|boto3|ses\.|gmail|twilio|"
                       r"messages\.send|smtp\.)", re.I)


def code_files():
    for d in ("cr", "web", "bench", "eval", "scripts", "studio"):
        for f in (ROOT / d).rglob("*"):
            if f.suffix in (".py", ".sh", ".js", ".html") and "static/cytoscape" not in str(f) and ".venv" not in f.parts:
                yield f


def test_no_send_path_exists():
    hits = [f"{f.relative_to(ROOT)}:{i}" for f in code_files()
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1) if FORBIDDEN.search(line)]
    assert hits == [], hits


def test_export_only_writes_a_file():
    src = (ROOT / "cr" / "outreach.py").read_text()
    assert "write_text" in src and "NOT SENT" in src
    assert not re.search(r"^\s*(import|from)\s+(httpx|requests|urllib)", src, re.M)


def test_server_forces_ask_first():
    assert 'req.outreach = "ask_first"' in (ROOT / "web" / "app.py").read_text()


def test_studio_forces_ask_first():
    src = (ROOT / "studio" / "web" / "app.py").read_text()
    assert src.count('.outreach = "ask_first"') >= 2  # Brainstorm runs and Explore runs
