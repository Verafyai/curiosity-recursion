# Curiosity Recursion: automating the "go deeper" loop

*Rex St. John, 26 November 2026. Version 0.1.0.*

## 65 relatives and one sentence typed a hundred times

I spent a long stretch researching 65 of my own relatives with an AI assistant. Some of them were
easy: a Civil War soldier with a regimental history, a grandmother with an obituary. Most were not.
They were immigrants whose names were spelled four ways, farmers who appear in one census and vanish,
women recorded only as "wife of".

The assistant was very good at one pass. Give it a name and it would come back with a census line, a
grave, a book that mentions the regiment, and a tidy paragraph. Then it would stop.

What I actually did, for weeks, was supervise. I typed the same handful of messages again and again:

- **"Go deeper."** You found the regiment. Which books cover it? Does one of them name him? On which page?
- **"Are you sure?"** That "Erastus Burnham, son of Phineas" may be a different man with the same name.
- **"Did you check the churches?"** There is a whole class of record you have not touched.
- **"Did that archive ever reply?"** The county clerk said three to four weeks. It has been five.
- **"Keep going."**

Each nudge took two seconds to type. Each one, when I forgot it, cost a record. And they were not
random: they were the same few moves, applied to whatever the last answer happened to be. That is
the part that made me think it could be automated.

## The black box stops early

A research agent is a black box that decides on its own when it is done. For most questions that is
fine. For genealogy it is the wrong default, because so much of the record is **dark data**:

- scanned but never indexed (a county history where your ancestor is on page 412),
- held by a small archive that answers a letter weeks later,
- behind a login or a reading room,
- or in a family box that only a cousin knows about.

A single confident pass cannot reach most of that. The human who keeps asking "what does this
finding make you want to check next?" sometimes can. So the useful thing to build is not a smarter
single pass; it is the loop the human was running.

## Circuits: writing down "did you check the churches?"

The first nudge to automate is the checklist one. Every experienced genealogist carries a list in
their head for each kind of life. For a Civil War soldier: unit and service dates, pension file,
burial, the census households before and after, the regimental history. For an immigrant: birthplace
abroad, the passage and arrival, naturalisation, where they settled, the church, the obituary.

In Curiosity Recursion those lists are **circuits**: YAML files with steps. Some steps are live
(public, keyless sources: Internet Archive full text, Chronicling America newspapers, Wikidata). Some
are honest stubs with a reason ("pension files need a request to the National Archives") that turn
into outreach drafts for a person to approve.

## Curiosity recursion: writing down "go deeper"

The second nudge is the interesting one. "Go deeper" means: take what you just found and ask the next
question it raises. CR makes that an explicit **question graph**:

1. Every finding can spark follow-up questions. A regiment sparks "which books cover the 12th
   Connecticut?". A book hit sparks "search inside that book for his name". A line reading "son of A
   and B" sparks "who were A and B?".
2. **Every question must quote its spark.** A question that cannot point to the words that raised it
   is rejected in code. This is what keeps the loop from drifting into plausible nonsense.
3. **Every question is deduplicated** against a persisted memory of every question asked before, in
   this run and earlier ones. "Go deeper" should not mean "ask the same thing again".
4. **"Are you sure?" is a node type.** Each finding gets a verification question, and a conflict
   check compares the dates in a lead's passage with the documented ones.
5. The graph expands under explicit limits: breadth `b` per level, depth `d`, total nodes `N`, a
   tool-call budget `B`, and a time limit. It stops when nothing new is left, and says so.

That conflict check earned its place early. In one run, the generator asked about "his parents, Amos
and Martha (Billings) Burnham" from a line that was actually about a different Burnham. After a fix
it found "(VI) Erastus W. Burnham, son of Phineas and Abigail (Huntley) Burnham", which looked right,
until the evidence layer read the rest of the passage: "born April 15, 1810, and died October 20,
1854". Our Erastus was born in 1834 and died in 1921. The report now names both conflicts and keeps
the parents as a lead, not a fact.

## Why it runs on Temporal: writing down "did they reply?"

The last nudges are about time. "Did that archive ever reply?" and "keep going" are what you say when
a process is long, flaky and waiting on people. That is what durable execution is for, so CR runs as
a Temporal workflow:

- **Crashes.** Kill the worker with `kill -9` in the middle of a run. Temporal holds the run; when the
  worker comes back it replays the history and continues from the same node. Finished lookups are not
  run again.
- **Flaky archives.** Each lookup is an activity with retries. The graph shows "retrying 3/8" on the
  node, read live from Temporal.
- **Letters.** An outreach draft waits for approval, then the run waits on a durable timer or a reply
  signal, for days if needed, at no cost.
- **People.** Approve, reject, or "Dig here first" are signals. The human stays in the loop, but as
  an editor, not as the engine.
- **Audit.** The event history records every question, lookup and retry. "How did it find this?" has
  an exact answer.

## Measuring it: DarkKin-Bench

A loop that feels more thorough is not the same as a loop that finds more. So I wrote a benchmark
and preregistered the hypotheses, budgets and tests before running it (commit `b06a658`).

**DarkKin-Bench v0** has 39 deceased subjects and 671 hidden records, stratified by how dark the
record is (T0 indexed and easy, up to T3 offline, needs a letter). The agents get the same tool-call
budget and are scored on how many hidden records they surface:

| Label | Agent |
| --- | --- |
| B0 | single-pass LLM with tools |
| B1 | ReAct LLM agent |
| B3 | checklist only (circuits, no recursion) |
| B4 | CR in a plain asyncio loop, no persistence (fault experiment only) |
| B5 | full CR on Temporal, preregistered settings (rule generator, b=3, d=3, N=80) |
| B5-max | post hoc: the widest graph the request allows (b=8, d=4, N=80), not preregistered |

<!-- RESULTS:BEGIN -->
(generated by scripts/readme_results.py from results/v0/results.json)
<!-- RESULTS:END -->

## What I learned

- **Durability is the easy win.** Killing the worker repeatedly did not cost CR on Temporal any
  finished work. The same loop without persistence had to start over each time.
- **Recursion beats a checklist, but the rule generator is not yet better than a good model's
  single pass.** That is the honest result of v0. The question graph is the right shape; the
  generator that fills it needs to be smarter, and the grounded model generator is the next thing
  to measure at scale.
- **The preregistered graph was too small.** With b=3 and d=3 the rule generator ran out of new
  questions at about 25 tool calls, so a bigger budget bought nothing. That is a finding about the
  stopping rule, not a bug in the comparison, and the post hoc wider configuration is reported next
  to it rather than instead of it.
- **Most dark records are still dark.** T2 and T3 records (offline, letter-only) have no URL to
  match, so no agent scores on them automatically. Reaching them is what the outreach and reply
  machinery is for, and measuring it needs human adjudication.

## Try it

```bash
temporal server start-dev --ui-port 8233
scripts/run-local.sh        # Builder on http://localhost:8090
```

Then type a name, pick Brainstorm, and kill the worker halfway through to watch it carry on. The code,
the paper, the benchmark harness and the public part of the data are in this repository under
Apache-2.0.
