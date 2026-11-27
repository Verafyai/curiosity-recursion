"""Evidence model (handoff 4f): leads versus facts, named conflicts, and the validator.

Run: .venv/bin/python -m pytest -q tests   (or: .venv/bin/python tests/test_evidence.py)
The snippets are verbatim from live Internet Archive hits in run studio-erastus-w-burnham-1126-105940.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.evidence import detect_conflicts, extract_leads
from studio.models import Citation, Claim, ComposeInput, Finding, GateResult, Person, Plan, Question, ResearchRequest, Sentence
from studio.writer import check_sentence, compose

ERASTUS = Person(full_name="Erastus W. Burnham", name_variants=["Erastus Burnham", "Erastus Williams Burnham", "E. W. Burnham"],
                 birth_year=1834, death_year=1921, family_notes="Whaler out of New London. Civil War surgeon for four years.")
ENCYC = ("James; Theron H. ; Gil- bert W. (VI) **Erastus W. Burnham, son of** Phineas and Abigail (Huntley) Burnham, "
         "was born April 15, 1810, and died October 20, 1854. He resided at South Windsor, Connecticut")
SIBLING = "Lois E. Burnham, daughter of Amos and Martha (Billings) Burnham, married Erastus W. Burnham of South Windsor"
ROSTER = "Oscar N. Bishop, Austin Brookman, James Burke, John Burnham, Erastus W. Carlan, John Carter, Henry B. Campbell"
OTHER_PARENTS = "Erastus W. Burnham, son of Elisha and Lucy Burnham, of East Windsor"


def doc(id_, field, text, year):
    return Claim(id=id_, field=field, text=text, tier="documented", year=year, origin=f"fixture:test#{id_}",
                 citation=Citation(title="Wood Memorial Library person record"))


FACTS = [doc("b01", "birth", "Born 28 April 1834", 1834), doc("b02", "death", "Died 11 April 1921, South Windsor", 1921),
         doc("b05", "military", "Private, Company A, 12th Connecticut Volunteer Infantry, enlisted 28 December 1861", 1861)]


def q(id_, *snippets):
    return Question(id=id_, key=id_, round=1, text="t", because="b", template="test", plan=Plan(handler="ia_fulltext"),
                    status="answered", citations=[Citation(title=f"Book {id_}", url=f"https://archive.org/details/{id_}",
                                                           item_id=id_, snippet=s) for s in snippets])


def test_parents_lead_is_possible_with_quote():
    leads = extract_leads(ERASTUS, [], [q("you17", ENCYC)])
    parents = [l for l in leads if l.field == "parents"]
    assert len(parents) == 1
    assert parents[0].tier == "possible"
    assert "Phineas and Abigail (Huntley)" in parents[0].text
    assert "son of Phineas and Abigail (Huntley) Burnham" in parents[0].quote


def test_sibling_line_is_not_his_parents():
    leads = extract_leads(ERASTUS, [], [q("x1", SIBLING)])
    assert not [l for l in leads if l.field == "parents"]


def test_second_parent_pair_is_a_named_conflict():
    leads = extract_leads(ERASTUS, [], [q("you17", ENCYC), q("x2", OTHER_PARENTS)])
    conflicts = detect_conflicts(FACTS, leads)
    pc = [c for c in conflicts if c.field == "parents"]
    assert len(pc) == 1
    assert "Phineas" in pc[0].label and "Elisha" in pc[0].label
    assert len(pc[0].claim_ids) == 2  # both stay


def test_snippet_date_never_overrides_the_record_and_is_named():
    leads = extract_leads(ERASTUS, [], [q("you17", ENCYC)])
    conflicts = detect_conflicts(FACTS, leads)
    birth = [c for c in conflicts if c.field == "birth"][0]
    assert "1810" in birth.label and "1834" in birth.label
    assert "b01" in birth.claim_ids
    parents = [l for l in leads if l.field == "parents"][0]
    assert parents.id in birth.claim_ids  # the same passage's parents lead is pulled into the conflict


def test_roster_match_is_a_lead_with_a_check_note():
    # Verbatim from page image 14 of the 12th Connecticut regimental history: a surname-first roster,
    # so "Burnham, Erastus W." is a real entry. It stays a candidate lead and asks for a check.
    leads = extract_leads(ERASTUS, [], [q("r3.2", ROSTER)])
    assert leads and leads[0].confidence == "candidate" and "comma separated list" in leads[0].matched_by


def test_validator_rejects_a_sentence_citing_a_lead():
    leads = {l.id: l for l in extract_leads(ERASTUS, [], [q("you17", ENCYC)])}
    lead_id = next(iter(leads))
    claims = {c.id: c for c in FACTS}
    assert check_sentence(Sentence(text="His parents were Phineas and Abigail Burnham.", claim_ids=[lead_id]), claims, leads) \
        == "cites a possible lead, not a record"
    assert check_sentence(Sentence(text="Born 28 April 1834.", claim_ids=["b01", lead_id]), claims, leads) \
        == "cites a possible lead, not a record"
    assert check_sentence(Sentence(text="Born 28 April 1834.", claim_ids=["b01"]), claims, leads) is None


def test_validator_other_rules():
    inferred = Claim(id="i1", field="parents", text="Probably Phineas", tier="inferred", origin="agent",
                     citation=Citation(title="reasoning"))
    told = Claim(id="t1", field="family_story", text="Whaler out of New London", tier="told", origin="user:form",
                 citation=Citation(title="Family notes"))
    claims = {c.id: c for c in [*FACTS, inferred, told]}
    assert check_sentence(Sentence(text="He served.", claim_ids=[]), claims) == "no claim cited"
    assert check_sentence(Sentence(text="Phineas was his father.", claim_ids=["i1"]), claims) == "cites an inferred claim, which is never published"
    assert check_sentence(Sentence(text="He was a whaler out of New London.", claim_ids=["t1"]), claims) == "family tradition told in the narrative voice"
    assert check_sentence(Sentence(text="Your family remembers that he was a whaler out of New London.", claim_ids=["t1"]), claims) is None
    assert check_sentence(Sentence(text="He must have felt proud when enlisted 28 December 1861.", claim_ids=["b05"]), claims) == "an interior state no record states"
    assert check_sentence(Sentence(text="Born 28 April 1835.", claim_ids=["b01"]), claims) == '"1835" is not in the cited records'


def test_compose_keeps_leads_out_of_the_text():
    req = ResearchRequest(person=ERASTUS, circuit_id="civil_war_veteran")
    finding = Finding(step_id="vital", step_title="Vital", stage=2, source_slug="none", mode="stub", status="found",
                      confidence="documented", claims=FACTS)
    rep = compose(ComposeInput(request=req, gate=GateResult(allowed=True, rule="death", reason="ok"), catalog=None,
                               findings=[finding], questions=[q("you17", ENCYC), q("x2", OTHER_PARENTS)]))
    text = " ".join(s.text for sec in rep.sections for s in sec.sentences)
    assert "Phineas" not in text and "Elisha" not in text and "1810" not in text
    lead_ids = {l.id for l in rep.leads}
    assert not any(i in lead_ids for sec in rep.sections for s in sec.sentences for i in s.claim_ids)
    assert {c.field for c in rep.conflicts} >= {"parents", "birth"}
    assert "Your family remembers that" in text
    assert rep.stats.uncited == 0
    assert "POSSIBLE" in rep.markdown and "Conflicts" in rep.markdown


def test_living_person_report_is_empty():
    p = Person(full_name="Jane Example", birth_year=1950)
    req = ResearchRequest(person=p, circuit_id="vital_records")
    rep = compose(ComposeInput(request=req, gate=GateResult(allowed=False, rule="living", reason="may be living"), catalog=None,
                               findings=[], questions=[]))
    assert rep.decision == "blocked" and not rep.sections and not rep.leads
    assert rep.lead == "This person may be living, so Lineage does not write about them."


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
