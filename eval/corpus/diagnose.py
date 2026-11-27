"""Why strategies differ: per-condition tool-use profile from the tool logs of a corpus-bench run.
Reports calls per run, share of calls that were exact repeats, share returning nothing, calls by
tool, and share of returned items naming the subject inside his life window. Aggregates only."""
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
    for tl in sorted((out / "logs").glob("*.tools.jsonl")):
        stem = tl.name[: -len(".tools.jsonl")]
        pid = stem.rsplit("-b", 1)[0].split("-")[-1]
        cond = stem.rsplit("-b", 1)[0][: -(len(pid) + 1)]
        pat = name_pattern(SUBJ[pid])
        lo, hi = LIFE[pid]
        calls, seen, rep, empty, items, on = 0, set(), 0, 0, 0, 0
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
            seen.add(sig)
            res = d.get("result")
            rows = res if isinstance(res, list) else list(res.values()) if isinstance(res, dict) else []
            empty += not rows
            for r in rows:
                items += 1
                t = norm(json.dumps(r))
                on += bool(pat.search(t)) and all(lo - 1 <= y <= hi + 40 for y in years(t) if y < 1990)
        A = agg[cond]
        A["calls"].append(calls)
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
    (out / "diagnose.json").write_text(json.dumps(res, indent=1))
    keys = ["runs", "calls", "repeat_share", "empty_share", "items", "on_target_share", "fn:ia_fulltext", "fn:ia_inside", "fn:chronam", "fn:ia_title_search", "fn:wikidata_search", "fn:wikidata_entities"]
    print("| condition | " + " | ".join(keys) + " |")
    print("|---|" + "---|" * len(keys))
    for c, r in res.items():
        print(f"| {c} | " + " | ".join(str(r.get(k, 0)) for k in keys) + " |")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
