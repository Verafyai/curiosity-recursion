# Changes, 26 Nov 2026 (Claude session)

Scope: handoff 4(a) branding, then 4(f) evidence model, as section 6 of HANDOFF-CLAUDE.md asks.
Nothing was sent, bought, pushed or written to Lineage production. No workflow code changed, so
existing histories replay unchanged (checked, see Verified).

## 4(a) Lineage Studio branding

- `web/static/studio.css` rewritten as the one token file: the kin `.lineage` scope exactly
  (#14110e ground, warm ink, #3a3128 rules, #e08a66 terracotta, evidence tier colours, frontier).
  Button gradient and shadow, header background and every other colour are tokens here. No colour
  literals anywhere else in `web/`.
- Fonts: Fraunces (normal and italic) and Public Sans, latin subset, self-hosted in
  `web/static/fonts/` so the demo works offline (SIL OFL). Body 17px, line height 1.6.
- Chrome: sticky 64px header with blur, the Lineage logo (`web/static/lineage-logo.svg`, also the
  favicon) and the "Lineage Studio" wordmark. Pill buttons: `.btn-primary`, `.btn-secondary`.
- Graph: Cytoscape reads node colours from the CSS tokens at runtime (answered `--documented`,
  running `--accent`, retrying `--warn`, no lead `--ink-3` on `--rule`, stub dashed `--lore`,
  error `--live`, queued `--frontier`). The state word is always on the node. Edges are calm
  right-angle connectors; no animation. Tall graphs keep a readable zoom (at least 0.62) and
  anchor top left instead of shrinking to unreadable.
- Status labels are catalogue-card chips with a dot plus the word. The run summary is a `dl`
  masthead ("Nodes 23 of 30"), not a progress bar.
- Report is now the Studio panel: "Make something from this", the `studioLead()` wording ported
  exactly (`studio_lead()` in `studio/writer.py`), the three cards with kin blurbs and thresholds
  ("Needs 6 more sourced facts. Has 2 of 8." and "More research will open this." below threshold,
  dashed "Coming soon" documentary), tier chips on every source, family words in display italic
  with a 2px accent rule, the kin proof line ("10 claims used, 10 footnoted, 0 uncited sentences."),
  footnotes numbered in reading order.
- Living gate copy: "This person may be living, so Lineage does not write about them."
- Start form: added the "What the family says" field (the model already had `family_notes`).
- When the worker is down the status chip reads "held by Temporal, worker down".
- No em-dash (U+2014) in `web/`, `studio/` or `README.md` (grep returns nothing).

## 4(f) Evidence model

- `studio/models.py`: `Tier` adds `possible` and `inferred`; `PUBLISHABLE_TIERS`; new `Lead`
  (quote, span, source id, confidence, matched_by, question id) and `Conflict`;
  `StudioReport.leads` and `.conflicts` (defaults, so old payloads still load).
- `studio/evidence.py` (new): extracts parents, birth, death and mention leads from every snippet;
  parents need the subject's given name just before "son of"; a match inside a comma separated
  roster keeps a note to check the list's name order on the page; conflicts are named for two parent pairs, for
  lead dates against documented dates, and for disagreeing lead dates; leads from the same passage
  join the conflict. Nothing is resolved or dropped.
- `studio/writer.py`: `check_sentence()` ports kin `validate.ts` checkSentence (no claim, cites a
  lead, cites inferred, interior state, causal link, family story outside the family frame, a
  number no record holds). Every narrative and family sentence passes through it. Family notes
  render as "Your family remembers that ...". The living report is emptied of leads and text.
- `tests/test_evidence.py` (9 tests) and `tests/test_replay.py` (Replayer over every run in the
  local Temporal).

### What it found on real data

Run `studio-erastus-w-burnham-1126-110934`, reviewer redirect "Does the Encyclopedia of
Massachusetts name his parents?": the passage reads "(VI) Erastus W. Burnham, son of Phineas and
Abigail (Huntley) Burnham, was born April 15, 1810, and died October 20, 1854." The record has
1834 to 1921. The report shows two named conflicts (birth and death) and pulls the
Phineas and Abigail parents lead into both. Another book names "Erastus Williams Burnham, (son of
Erastus W." and Burpee's has "Mr. Burnham's father, Erastus Williams Burnham, II, who was born
April 28, 1834". Read together these suggest Phineas and Abigail belong to an older Erastus W.
Burnham, but that is a reading of leads, not a finding, and the app does not state it.

## Correction (later the same day)

The first version of the evidence model marked the roster match on page image 14 of the 12th
Connecticut regimental history as weak, reading "John Burnham, Erastus W. Carlan" as a different
man. Reading the page again (via inside-book search), the roster lists surname first: "Burke, John
Burnham, Erastus W. Carlan, John Clark, Dallas", in alphabetical order. So "Burnham, Erastus W." is
a real roster entry. The weak flag was removed; the lead now carries a note to check the name order
on the page. It is still a lead, not an identification.

## Verified

- `tests/test_evidence.py`: 9 of 9 pass. `tests/test_replay.py`: all local histories replay.
- Full runs on a fresh local Temporal dev server (CLI 1.10.1, server 1.32.2, SDK 1.37.0):
  Erastus (23 then 25 nodes, 2 reviewer redirects, approved through the API), Mary Devine
  (crossing circuit, 2 Glasgow clerk drafts), Jane Example (blocked by the living gate).
- Worker `kill -9` twice: 11:12:34 AM PT on the Erastus run (194 events held, 2 lookups pending,
  restarted 11:12:52, carried on to completion) and 11:22:12 AM PT on the Mary run (158 events
  held, restarted 11:22:24). In-flight lookups were retried after their 90 second start-to-close
  timeout; finished ones were not repeated.
- Screenshots re-taken at 1440x900 headless Chrome and reviewed: `captures/01` to `11`. Fixed
  from review: unreadable tiny graph zoom, overlapping level-2 nodes, out-of-order footnotes,
  a long unstructured live-steps list, doubled full stops, a duplicated line in conflict notes,
  and the conflict chip picking up its box style.

## Not done, worth knowing

- Wikidata returns HTTP 429 to this sandbox's IP on every call; those checklist steps exhaust 8
  retries and show as failed. Not an app bug; it would also make a good live "source refused" demo.
- Event history for the deep Erastus run is 1.74 MB at 303 events (the handoff estimated about
  550 KB at 40 nodes). Continue-as-new (4h) matters sooner than expected.
- A heartbeat timeout on `investigate` would let a killed worker's lookups retry in seconds
  instead of 90.
- The "Ready to write" button is disabled: writing belongs to 4(g).
