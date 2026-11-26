# Adjudication guide

Two raters label every item independently, blind to which agent produced it. At least one rater
is an experienced genealogist who did not build the system. Target Cohen's kappa of at least 0.7
before scoring; a third rater resolves disagreements into `final_label`.

## Labels

| label | meaning |
| --- | --- |
| correct_same_person | the record exists, says what is claimed, and is about this person |
| correct_record_wrong_person | the record exists but is about someone else (count as wrong person) |
| real_source_not_supporting | the source exists but does not contain or support the claim |
| source_does_not_exist | no such source, or no such text in it (count as hallucination) |
| identified_request_drafted | T2 or T3: the right holder and record are named and a correct request is drafted |
| cannot_determine | not enough to decide |

## How to judge "same person"

Name alone is never enough. Look for at least two agreeing details from the subject card or the
documented record: birth or death year within a year, a place, a spouse, a unit, an occupation.
A surname match is never a family link. If two details disagree, label it wrong person and note
which details.

## Files

`make_sheet.py` writes one CSV per rater from a results file (agent names replaced by random
codes). `kappa.py` reads two filled sheets and prints kappa per label set.
