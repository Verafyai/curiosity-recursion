# Datasheet: DarkKin-Bench v0

Following Gebru et al., Datasheets for Datasets (CACM 2021). v0 is internal; v1 is the public release.

## Motivation

- **Why:** to measure whether a research agent finds records of deceased people that are hard to
  find (full text only, gated, or offline), not only records a single index search returns.
- **Who built it:** Rex St. John, from kin eval files. The heritage subjects were researched by
  separate agents from Wikipedia, Wikidata and the archives themselves, not by the code builder
  (kin's own note). The family dossiers were built by Rex from his Book-o-Matic research.

## Composition

- 39 subjects (`bench/data/stats.json`): 4 family dossier subjects and 35 public historical figures
  in five groups (jewish, academic, immigrant, military, control), 7 each.
- 671 hidden records. Darkness tiers by host rule: T0 156, T1 467, T2 17, T3 31. No tier is
  confirmed by a person yet (`confirmed: false` on every record).
- Birth eras: 9 before 1850, 18 from 1850 to 1899, 12 from 1900 to 1949.
- Circuits: 32 vital_records, 7 the_crossing. No military subject was born in the Civil War
  window, so v0 has no subject on the civil_war_veteran circuit; WWI, WWII and Korea circuits do
  not exist yet.
- **Subject card** (what the agent gets): name, birth and death years, birth and death places.
  kin's Wikipedia and Wikidata ids are withheld, because they would hand over ground truth.
- **Record** (hidden): key, host, URL and title where public, tier, kin's reach label, and flags.
- **Splits:** 27 dev, 12 test, by a fixed hash of the subject id. kin's 15-subject holdout file is
  sealed and unread (hash in `PREREGISTRATION.md`).

## Known problems

- Family dossiers include period-context sources (for example census bureau pages, a
  public-health page) next to records about the person. `about_subject` is unset for those 523
  records until a reviewer marks it.
- Tiers come from a host rule, not a reading of each record. Some "T1" pages are catalogue
  entries that an index search would find.
- Skew: United States and Canada, English-language sources, New England heavy.
- Small n. The author built the system and much of the ground truth; independent raters and the
  sealed holdout are the mitigation.

## Collection and living people

- Every subject passed the living-person gate (death on record, or birth at least 110 years
  ago); the log is `bench/data/build.log`. Unknown dates default to living.
- Family dossier titles are never released, because a title can name a living relative (for
  example an interviewee). Private items (interviews, photo boxes, local files) are released as
  counts and tiers only: 32 such records in v0.

## Uses

- For: comparing research agents at equal budget, by tier, with adjudicated scoring.
- Not for: identity resolution claims without adjudication; anything about living people;
  training a model to reproduce a family's private records.

## Distribution and maintenance

- Code under Apache-2.0. Public subject cards and public record keys and URLs only. Contact:
  Rex St. John. Versioned (v0 internal, v1 public); errata appended, never rewritten.
