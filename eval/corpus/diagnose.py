"""Why strategies differ: per-condition tool-use profile from the tool logs of a corpus-bench run.
Reports calls per run, share of calls that were exact repeats, share returning nothing, calls by
tool, and share of returned items naming the subject inside his life window. Aggregates only.
v0.2 adds: repeats excluding retries (a call repeating one that had failed is a retry, not waste), HTTP 429
counts (all hosts and Wikidata only) per run in diagnose-runs.json, and error share."""
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.corpus.score import _salvage, name_pattern, norm, years  # noqa: E402

LIFE = {"burnham": (1834, 1921), "homer": (1900, 1972), "john": (1921, 2006), "kingsley": (1907, 1962), "bristol": (1871, 1944), "alex": (1967, 2026)}
SUBJ = {"burnham": "Erastus William Burnham", "homer": "Homer Doble St. John", "john": "John St. John", "kingsley": "Kingsley Arnold Perry",
        "bristol": "Edgar Hiel Bristol", "alex": "Alex St. John"}


def main(out: Path):
    agg = defaultdict(lambda: defaultdict(list))
    per_run: dict = {}
    for tl in sorted((out / "logs").glob("*.tools.jsonl")):
        stem = tl.name[: -len(".tools.jsonl")]
        pid = stem.rsplit("-b", 1)[0].split("-")[-1]
        cond = stem.rsplit("-b", 1)[0][: -(len(pid) + 1)]
        pat = name_pattern(SUBJ[pid])
        lo, hi = LIFE[pid]
        calls, seen, rep, empty, items, on = 0, set(), 0, 0, 0, 0
        rep_nr, errs, h429, wd429 = 0, 0, 0, 0
        last_ok: dict = {}
        fn = Counter()
        for line in tl.read_text().splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                d = _salvage(line) or {"fn": "unparsed", "args": [], "result": []}
            calls += 1
            fn[d["fn"]] += 1
            sig = (d["fn"], tuple(d.get("args") or ()), tuple(sorted((d.get("kwargs") or {}).items())))
            rep += sig in seen
            rep_nr += sig in seen and last_ok.get(sig, False)
            seen.add(sig)
            err = str(d.get("error") or "")
            last_ok[sig] = last_ok.get(sig, False) or not err
            errs += bool(err)
            if "HTTP 429" in err:
                h429 += 1
                wd429 += "wikidata" in err or d["fn"].startswith("wikidata")
            res = d.get("result")
            rows = res if isinstance(res, list) else list(res.values()) if isinstance(res, dict) else []
            empty += not rows
            for r in rows:
                items += 1
                t = norm(json.dumps(r))
                on += bool(pat.search(t)) and all(lo - 1 <= y <= hi + 40 for y in years(t) if y < 1990)
        A = agg[cond]
        A["calls"].append(calls)
        A["repeat_share_excl_retries"].append(rep_nr / calls if calls else 0)
        A["error_share"].append(errs / calls if calls else 0)
        A["http429"].append(h429)
        A["wikidata_429"].append(wd429)
        per_run[stem] = {"condition": cond, "person": pid, "calls": calls, "exact_repeats": rep, "repeats_excl_retries": rep_nr,
                         "errors": errs, "http429": h429, "wikidata_429": wd429}
        A["repeat_share"].append(rep / calls if calls else 0)
        A["empty_share"].append(empty / calls if calls else 0)
        A["items"].append(items)
        A["on_target_share"].append(on / items if items else 0)
        for k, v in fn.items():
            A["fn:" + k].append(v)
    res = {}
    for c, A in agg.items():
        n = len(A["calls"])
        res[c] = {k: round(sum(v) / n, 3) for k, v in A.items()}
        res[c]["runs"] = n
    for c in res:
        res[c]["http429_total"] = sum(agg[c]["http429"])
        res[c]["wikidata_429_total"] = sum(agg[c]["wikidata_429"])
    (out / "diagnose.json").write_text(json.dumps(res, indent=1))
    (out / "diagnose-runs.json").write_text(json.dumps(per_run, indent=1))
    keys = ["runs", "calls", "repeat_share", "repeat_share_excl_retries", "error_share", "http429_total", "wikidata_429_total", "empty_share", "items", "on_target_share", "fn:ia_fts", "fn:ia_fulltext", "fn:ia_inside", "fn:ia_inside_pages", "fn:chronam", "fn:ia_title_search", "fn:wikidata_search", "fn:wikidata_entities"]
    print("| condition | " + " | ".join(keys) + " |")
    print("|---|" + "---|" * len(keys))
    for c, r in res.items():
        print(f"| {c} | " + " | ".join(str(r.get(k, 0)) for k in keys) + " |")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
