# Corpus-replication eval: specification (answer key v1)

The question this eval answers: **given only a name and a birth year, how much of a hand-built
family dossier does one pass of a research strategy recover?** 100% means it found everything in
the dossier, or pointed to exactly where to get it.

## 1. Gold set

Six hand-curated dossiers from the Book of Daniel family history, chosen to span eras:

| ID | Person | Era | Gate basis |
|---|---|---|---|
| burnham | Erastus William Burnham (1834-1921) | Civil War | death on record |
| homer | Homer Doble St. John (1900-1972) | WWI | death on record |
| john | John St. John (1921-2006) | WWII | death on record |
| kingsley | Kingsley Arnold Perry (1907-1962) | civilian | death on record |
| bristol | Edgar Hiel Bristol (1871-1944) | civilian | death on record |
| alex | Alex St. John (born 1967) | civilian | family attestation (no death record in the dossier) |

## 2. Answer key (`eval/answer_keys/v1/`)

- `eval/corpus/atomize.py` splits each dossier into body and numbered references and has a model
  (temperature 0, one call per ~3,000 characters) list atomic facts: person, relation, type,
  value, date, place, keywords, and the reference numbers that support it.
- `eval/corpus/freeze.py` attaches each reference as a source with an **access tier**, applies the
  **living-person gate** to every person a fact names, marks **holdout** facts, and writes the key
  plus `LOCK.json` (SHA-256 of every file). Versions are never edited in place; a change is a new
  version (`v2/`), so scores stay comparable.
- **Access tiers** (rules in `freeze.py:tier`): `outreach` (interviews, family papers, anything
  "supplied by" an archive or clerk, and the dossier author's own site), `web_gated` (Ancestry,
  FamilySearch, NewspaperArchive, ProQuest, Fold3, GenealogyBank, MyHeritage), `book` (archive.org,
  HathiTrust, Google Books, Gutenberg, or a printed-book citation), `web_open` (any other URL).
  Books appear only as citations and identifiers; no book text is stored.
- **Privacy gate.** A fact is public only if every person it names has a death on record or a
  birth 110+ years ago (unknown birth counts as living). Facts naming anyone else, and anything
  naming the author's children, go to `eval/private/` (gitignored). Private facts count in local
  scores; the public leaderboard shows only aggregates.
- **Holdout.** `sha256("cr-holdout-v1:" + fact_id) mod 10 < 3` marks about 30% of facts as
  holdout. Strategy authors must not look at holdout facts; the leaderboard reports holdout recall
  separately.

## 3. Input and conditions (identical for every strategy)

- Input card (`eval/corpus/subjects.jsonl`): full name and birth year only. John and Alex carry a
  `death_on_record` flag so the gate can pass without revealing a date.
- Tools: Wikidata search and entities, Internet Archive title search, full-text search and
  search-inside, and Chronicling America (loc.gov). Nothing else.
- Budget: the same tool-call budget B (default 100) and the same wall-clock cap.
- Runs: at least 3 per strategy per person; mean and standard deviation are reported.
- Memory: each run gets a fresh tag, so no strategy sees another run's questions.

## 4. Exclusion filter (`cr/sources/exclusion.py`), on for every strategy

1. **Host blocklist.** Any query naming, or result item mentioning, rexstjohn.com and all its
   subdomains, verafy.ai / verafyai.com, any `*.vercel.app` deployment, github.com /
   raw.githubusercontent.com / gist for the rexsaurus, Verafyai and rexstjohn accounts, the
   x.com / twitter.com accounts rexstjohn, verafyai and verafyfoundtn, and web.archive.org /
   archive.today snapshots of any of those, is dropped.
2. **Content guard.** Any returned item sharing at least 5 distinct word 8-grams, and at least 20%
   of its 8-grams, with the dossier author's own prose (all 95 pages of his family site, with
   quoted passages and reference lists removed first) is dropped. Only 64-bit hashes of 8-grams are
   stored (`eval/exclusion/build_ngrams.py`), never the text.
3. Every block or drop is logged to `blocked.jsonl` per run; the leaderboard reports counts.

Calibration (26 Nov 2026): on 309 items from earlier tool logs, 0 were dropped (highest overlap
1.5%). 46 of 50 random 30-word passages of dossier prose were dropped. 2 of 6 long quotations
from primary sources inside a dossier were also dropped, so a strategy can lose a real find that
the dossier quotes word for word; that cost falls on every strategy equally.

## 5. Scoring (`eval/corpus/score.py`)

Evidence is every item the tools returned during the run (from the tool log, after the filter).
Names are normalised (St./Saint/St, Erasthus/Erastus, accents, initials), and dates are compared
by year.

- **1.0**: a returned item names the person (given name or initial, a middle name or initial that
  agrees with the known one, and the surname) and, within about 60 words of that mention, carries
  the fact's year (when it has one) and enough of the fact's content words (at least half, between
  1 and 4). Name facts need the exact name form stated.
- **0.5**: not found, but the run reached one of the fact's own key sources (same IA identifier,
  loc.gov page or URL) with the person named; or, for book and outreach facts, the run cited the
  right book identifier or named the right archive in an outreach draft or its answer.
- **0**: otherwise.

Reported per person and strategy: % of dossier recovered (mean and sd), full-credit-only recall,
holdout recall, recall by access tier, source recall (key sources with a machine-readable
identifier that were reached), precision of reported items (names the subject and has no year
outside the life window), novel candidates (on-target reported items matching no key source and
no fact; candidates, not verified finds), false family links (relation claims naming someone
outside the key's family), and a penalised score = recall - 5 x false links / facts. The overall
score is the mean over people; era scores average the people in each era.

**Scorer audit.** `eval/corpus/audit.py` samples about 20 decisions per person (half credited, half
hard negatives where a returned item names the person) and asks an independent model judge,
which does not see the scorer's decision, whether the evidence states the fact. Agreement and
Cohen's kappa are reported. This is a model audit, not a human one.

## 6. Running it

    scripts/run-bench.sh --people burnham,homer,john,kingsley,bristol,alex \
        --conditions B0,B1,B3,B5,B5-max,B5-fix --runs 3 --budget 100

It runs every strategy (each run its own process with its own tool and block logs), scores them,
writes `benchmark/results/<answer-key>/<stamp>/results.json`, regenerates
`benchmark/index.html` and `benchmark/BENCHMARK.md`, regenerates the paper's tables and rebuilds
the PDF. The private parts of the key and the per-fact tables stay on your machine.

## 7. Known limits of v1

- The key is model-atomized and not yet reviewed by the dossier author; some facts repeat.
- The tool set cannot reach most dossier hosts (Find a Grave, FamilySearch, Library and Archives
  Canada, NARA, Wood Memorial), which caps every strategy. The share of facts with a source on a
  reachable host is in `answer-key-review.md`.
- The scorer is lexical; the audit measures how often it agrees with a judge.
- Alex St. John's gate rests on family attestation only.
