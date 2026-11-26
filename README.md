# curiosity-recursion

Durable, grounded question graphs for long-running archival research, on Temporal.

You put in the name of someone who has died. The system runs a baseline checklist for their
heritage group (a **circuit**), then keeps asking new questions sparked by what it finds
(**Curiosity Recursion**): "he served in the 12th Connecticut, so which books cover that regiment,
does any of them name him, on which page?". Every question must quote the finding that sparked it,
is deduplicated against every question asked before, and is chased as a retried, recorded step.
It runs for as long as you allow, survives crashes, waits on durable timers, and stops for your
approval. Nothing is ever sent.

This is the reference code for the paper *Curiosity Recursion: Durable, Grounded Question Graphs
for Genealogical Dark Data* and the benchmark **DarkKin-Bench**.

## Quickstart (one machine, no keys)

```bash
temporal server start-dev --ui-port 8233          # Temporal CLI; leave it running
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export CR_CONTACT="you@example.org"               # a contact address for polite HTTP access
.venv/bin/python worker.py &                      # task queue: curiosity-recursion
.venv/bin/uvicorn web.app:app --port 8090 &       # live graph UI
.venv/bin/python start_run.py examples/erastus.json
# UI: http://localhost:8090   Temporal UI: http://localhost:8233
.venv/bin/python -m pytest -q tests               # 35 tests, including replay and no-send
```

Kill the worker mid-run (`kill -9`), start it again, and the run carries on from the same question.

## Layout

```
cr/
  models.py          every typed value that crosses Temporal (Pydantic), plus grounded()
  gate.py            living-person gate (unknown dates mean living)
  workflow.py        CuriosityRecursionWorkflow + ChecklistPassWorkflow
  activities.py      checklist steps, investigate, brainstorm, compose
  generators/        rules.py (default, no model), llm.py (grounded, key from env), dispatch
  novelty.py         canonical keys, near-duplicate test, novelty score
  memory.py          SQLite question memory (CR_DB)
  evidence.py        leads, conflicts, claim tiers, the sentence validator
  outreach.py        drafts only; approval writes a file; no mail transport exists
  writer.py          the report, from documented claims only
  circuits/*.yaml    circuits and steps (live or stub, with the reason)
  sources/           live.py (public keyless clients), mock_archive.py (bench only)
web/                 live graph UI (Cytoscape.js)
bench/               PREREGISTRATION.md, DATASHEET.md, schema/, data/, convert_kin.py,
                     harness.py, faults.py, baselines/
eval/                score.py, stats.py, plots.py, pilot_stats.py, adjudicate/
tests/               gate, grounding and dedupe, evidence, replay, time skipping, no send, scoring
```

## The run request

Every switch the paper ablates is a field of `ResearchRequest`: `depth`, `breadth`, `max_nodes`,
`max_tool_calls` (budget B), `max_run_minutes`, `level_pause_seconds`, `generator`
(`rules`, `llm`, `hybrid`), `use_memory`, `use_circuits`, `verify_nodes`, `dedupe`,
`use_fixtures` (always off in the benchmark), `llm_token_budget`.

## Benchmark

```bash
.venv/bin/python bench/convert_kin.py --relatives PATH/relatives.json --heritage PATH/heritage-real.json
.venv/bin/python bench/harness.py --agents B3,B5 --budgets 50,100 --split dev --out results/h1.jsonl
.venv/bin/python bench/faults.py --agent B5 --fault-p 0.3 --kill-every 45 --subjects kinher-jewish-01 --out results/h2.jsonl
.venv/bin/python eval/score.py results/h1.jsonl
```

`scripts/run_all.sh` runs everything in order. Read `bench/PREREGISTRATION.md` first: the
hypotheses, budgets and tests are fixed there before any run. The converter refuses any file whose
name contains "holdout". Automatic matches are candidates until two raters adjudicate them
(`eval/adjudicate/GUIDE.md`).

## Live and stub

| Source | Mode | Notes |
| --- | --- | --- |
| Internet Archive: catalogue search, full-text search, search inside one book | live, keyless | lending books refuse inside-book search (HTTP 403), recorded as "source refused" |
| Chronicling America via loc.gov JSON | live, keyless | about 30 s a query |
| Wikidata wbsearchentities, wbgetentities | live, keyless | some cloud addresses get HTTP 429 on every call |
| Optional public source catalogue (`CR_CATALOG_URL`) | live, keyless | off by default; read-only GETs |
| Vital records, census before 1950, parents, children, work, passenger lists, naturalisation, state roster | stub | demo mode reads `fixtures/burnham-erastus.json`; benchmark mode reads nothing |
| Find a Grave | stub | links only; terms prohibit automated access |
| Pension index, National Archives catalogue, local archive collections | stub | produce outreach drafts for a person to approve |
| Simulated archives (`cr/sources/mock_archive.py`) | bench only | answer drafts by signal after 3 to 21 simulated days |

## Rules this code keeps

- **Deceased people only.** The gate runs in workflow code before any lookup: a death on record
  (precision not "after"), or a birth at least 110 years ago. Unknown means living.
- **Leads are not facts.** A name in OCR text is a lead (`possible`), shown with its quote. A
  surname alone never links two people. Conflicts are named, never resolved. `inferred` is never
  published.
- **Ask first.** Outreach is drafted and held; approval writes a text file. No code path sends mail
  (`tests/test_no_send.py`).
- **No scraping where prohibited**, no captcha or paywall bypass, polite rate limits, a contact
  address in the user agent.
- **Keys stay in the worker's environment** and are optional.

## Known gaps

- The rule-based generator is the only one measured. The grounded model generator is built and
  unmeasured.
- Demo facts come from a fixture (labelled STUB); live sources add leads.
- No continue-as-new yet; a 25-node run reached 303 events and 1.74 MB of history.
- Activities have no heartbeat timeout, so a killed worker's in-flight lookup waits for its 90 s
  start-to-close timeout before it is retried.
- Wikidata rate limits from shared cloud addresses can fail the identity step in some runs and not
  others, which confounds agent comparisons. Run the benchmark from an address Wikidata does not
  throttle, or cache responses, and log the 429 count per run.
- A smoke run on 26 Nov 2026 (`results/smoke-2026-11-26.jsonl`, 3 dev subjects, B3 and B5 at
  B = 40) checked that the harness, scorer and logs work end to end. It is not a result: no
  adjudication, n = 3, and the Wikidata throttling above hit the B5 runs and not the B3 runs.

## License

Apache-2.0 (see `LICENSE` and `NOTICE`).
