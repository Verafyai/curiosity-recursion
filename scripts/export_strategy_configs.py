"""Write strategies/<name>/config.json from the harness's AGENT_CONFIG and request defaults, so the
config a strategy page shows is the config the benchmark ran."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.harness import AGENT_CONFIG  # noqa: E402

DEFAULTS = dict(depth=3, breadth=3, max_nodes=80, max_run_minutes=180, generator="rules", use_memory=True, use_circuits=True,
                verify_nodes=True, dedupe=True)
LLM = {"B0": dict(kind="llm", turns=1, prompt="bench/baselines/llm_agents.py SYSTEM + task string", temperature=1.0),
       "B1": dict(kind="llm", turns="until done or budget", prompt="bench/baselines/llm_agents.py SYSTEM + task string", temperature=1.0)}
for name in ["B0", "B1", "B3", "B4", "B5", "B5-max", "B5-fix", "B5-llm", "B6-swarm", "B6-no-ledger", "B6-no-parallel", "B6-no-reflect", "B6-v1tools"]:
    d = ROOT / "strategies" / name
    d.mkdir(parents=True, exist_ok=True)
    if name in LLM:
        cfg = {"agent": name, **LLM[name], "tools": ["wikidata_search", "wikidata_entities", "ia_title_search", "ia_fulltext", "ia_inside", "chronam"]
               + (["ia_fts"] if name == "B1" else [])}
    elif name == "B4":
        cfg = {"agent": "B4", "kind": "cr-asyncio", "note": "same loop as B5 in a plain asyncio process with no durable state (bench/baselines/cr_plain_loop.py); H2 only", **DEFAULTS}
    elif name.startswith("B6"):
        from cr.allocator import MIN_FIRST_ROUND, DRY_ROUNDS
        from cr.leads import UCT_C, VALUE_FLOOR, WEIGHTS
        from cr.ledger import K_EMPTY, MAX_HOPS, NEAR_JACCARD, NOVELTY_BY_KEY, PAGE_WINDOW
        cfg = {"agent": name, "kind": "cr-temporal-swarm", **AGENT_CONFIG[name],
               "value_weights": dict(zip(("w_novelty", "w_expected_yield", "w_reachability", "w_gap_fill", "w_cost"), WEIGHTS)),
               "uct_c": UCT_C, "value_floor": VALUE_FLOOR, "allocator": {"rule": "UCB1", "min_first_round": MIN_FIRST_ROUND, "dry_rounds": DRY_ROUNDS},
               "ledger_rules": {"k_empty": K_EMPTY, "page_window": PAGE_WINDOW, "max_hops": MAX_HOPS, "near_jaccard": NEAR_JACCARD,
                                "novelty_by_key": NOVELTY_BY_KEY}}
    else:
        cfg = {"agent": name, "kind": "cr-temporal", **DEFAULTS, **AGENT_CONFIG[name]}
    cfg["budget"] = "max_tool_calls = B (benchmark budget)"
    cfg["exclusion_filter"] = "cr/sources/exclusion.py (on for every strategy)"
    (d / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    print(name, cfg)
