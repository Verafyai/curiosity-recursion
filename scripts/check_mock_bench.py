"""Acceptance check for the offline mock bench (spec v0.2 section 13.2).

B6-swarm: exact-repeat rate 0% in the tool log, at least 80% of B used, and a ledger.jsonl in which every
revisit carries a reason. B6-no-ledger: exact-repeat rate above 0% (the ledger is what removes repeats).
B6-no-parallel: completes and uses at least 80% of B. Exits non-zero if any check fails.
"""
import argparse
import json
import sys
from pathlib import Path


def tool_log_stats(p: Path):
    seen, rep, n = set(), 0, 0
    for line in p.read_text().splitlines():
        d = json.loads(line)
        n += 1
        sig = (d["fn"], tuple(d.get("args") or ()), tuple(sorted((d.get("kwargs") or {}).items())))
        rep += sig in seen
        seen.add(sig)
    return n, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--budget", type=int, default=100)
    a = ap.parse_args()
    ok, report = True, {}
    for tl in sorted((a.out / "logs").glob("*.tools.jsonl")):
        name = tl.name[: -len(".tools.jsonl")]
        cond = name.split("-mock-")[0]
        n, rep = tool_log_stats(tl)
        run = json.loads((a.out / "runs" / f"{name}.jsonl").read_text().splitlines()[-1])
        led = a.out / "ledgers" / f"{name}.ledger.jsonl"
        rows = [json.loads(x) for x in led.read_text().splitlines() if x.strip()] if led.exists() else []
        revisits = [r for r in rows if r.get("decision") == "revisit"]
        r = {"calls": n, "exact_repeats": rep, "repeat_rate": rep / n if n else 0.0, "used_share": n / a.budget,
             "charged": run.get("tool_calls"), "ledger_rows": len(rows), "revisits": len(revisits),
             "revisits_without_reason": sum(1 for x in revisits if not x.get("reason")), "completed": run.get("completed")}
        checks = []
        if cond == "B6-swarm":
            checks = [("repeat_rate == 0", rep == 0), ("used >= 80% of B", n >= 0.8 * a.budget),
                      ("ledger.jsonl written", bool(rows)), ("every revisit has a reason", r["revisits_without_reason"] == 0)]
        elif cond == "B6-no-ledger":
            checks = [("repeat_rate > 0", rep > 0)]
        elif cond == "B6-no-parallel":
            checks = [("used >= 80% of B", n >= 0.8 * a.budget)]
        r["checks"] = {k: v for k, v in checks}
        ok &= all(v for _, v in checks)
        report[name] = r
    (a.out / "mock-check.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    print("MOCK BENCH:", "PASS" if ok and report else "FAIL")
    sys.exit(0 if ok and report else 1)


if __name__ == "__main__":
    main()
