"""Question memory M: every question ever asked, per person key, in SQLite.

`persist_run` writes every node after every level. `load_prior_questions` returns what
earlier runs asked about the same person (newest first, one per canonical key); the workflow
re-asks their top-level questions first and dedupes new ideas against all of them.
Set CR_DB to keep a separate store (the benchmark uses one per configuration and seed).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from temporalio import activity

from cr.models import PersistInput, PriorInput, PriorQuestions, Question

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.environ.get("CR_DB", ROOT / "data" / "cr.db"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def _db() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(
        """
        create table if not exists runs (workflow_id text primary key, person_key text, name text, circuit text, status text, updated_at text);
        create table if not exists questions (workflow_id text, node_id text, person_key text, key text, status text, depth int,
            text text, json text, updated_at text, primary key (workflow_id, node_id));
        create table if not exists outreach (workflow_id text, id text, status text, json text, updated_at text, primary key (workflow_id, id));
        """
    )
    return con


@activity.defn
async def persist_run(inp: PersistInput) -> int:
    con = _db()
    ts = now().isoformat()
    with con:
        con.execute("insert or replace into runs values (?,?,?,?,?,?)", (inp.workflow_id, inp.person_key, inp.person.full_name, inp.circuit_id, inp.status, ts))
        for q in inp.questions:
            con.execute("insert or replace into questions values (?,?,?,?,?,?,?,?,?)",
                        (inp.workflow_id, q.id, inp.person_key, q.key, q.status, q.depth, q.text, q.model_dump_json(), ts))
        for o in inp.outreach:
            con.execute("insert or replace into outreach values (?,?,?,?,?)", (inp.workflow_id, o.id, o.status, o.model_dump_json(), ts))
    con.close()
    return len(inp.questions)


@activity.defn
async def load_prior_questions(inp: PriorInput) -> PriorQuestions:
    """Questions earlier runs asked about the same person, newest first, one per key."""
    con = _db()
    me = activity.info().workflow_id
    rows = con.execute(
        "select workflow_id, json from questions where person_key=? and workflow_id != ? order by updated_at desc", (inp.person_key, me)
    ).fetchall()
    con.close()
    seen, out, runs = set(), [], []
    for wid, js in rows:
        q = Question.model_validate_json(js)
        if q.key in seen or q.status in ("pending", "running"):
            continue
        seen.add(q.key)
        q.seeded_from = wid
        out.append(q)
        if wid not in runs:
            runs.append(wid)
    return PriorQuestions(questions=out, runs=runs)


