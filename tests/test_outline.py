"""Outline: era-specific lanes, non-overlapping boundaries, stubs for offline record types."""
from cr.models import Person
from cr.outline import plan_outline


def test_civil_war_era_gets_a_military_lane_with_high_prior():
    o = plan_outline(Person(full_name="Josiah Quill Tester", birth_year=1840))
    ids = [l.id for l in o.lanes]
    assert "military" in ids and o.era == "Civil War"
    mil = next(l for l in o.lanes if l.id == "military")
    assert mil.prior >= max(l.prior for l in o.lanes if l.id != "military")
    assert any(s.to.startswith("National Archives") for s in mil.stubs)


def test_civilian_has_no_military_lane():
    o = plan_outline(Person(full_name="Marta Ellen Sample", birth_year=1950))
    assert "military" not in [l.id for l in o.lanes] or o.era != "civilian"
    o2 = plan_outline(Person(full_name="Marta Ellen Sample", birth_year=1902))
    assert o2.era == "World War II"


def test_boundaries_do_not_overlap():
    o = plan_outline(Person(full_name="Josiah Quill Tester", birth_year=1840))
    news = [l for l in o.lanes if l.viewpoint == "newspaper"]
    assert len(news) >= 2
    for a in news:
        for b in news:
            if a.id < b.id:
                assert a.date_window[1] < b.date_window[0] or b.date_window[1] < a.date_window[0]
    assert all(s.tool == "chronam" for l in news for s in l.seeds)
    assert all(s.tool != "chronam" for l in o.lanes if l.viewpoint != "newspaper" for s in l.seeds)
    assert all(s.tool.startswith("wikidata") for l in o.lanes if l.viewpoint == "reference" for s in l.seeds)
    assert all(l.boundaries for l in o.lanes)


def test_stubs_for_offline_record_types():
    o = plan_outline(Person(full_name="Josiah Quill Tester", birth_year=1840))
    stubbed = {l.id for l in o.lanes if l.stubs}
    assert {"probate", "church", "land"} <= stubbed
    assert any("FamilySearch" in s.to for l in o.lanes for s in l.stubs)


def test_input_card_only():
    a = plan_outline(Person(full_name="Josiah Quill Tester", birth_year=1840))
    b = plan_outline(Person(full_name="Josiah Quill Tester", birth_year=1840))
    assert a == b
