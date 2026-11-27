"""Search ledger: canonical form, repeat blocking, revisit keys with reasons, gate, foraging stop, suggest."""
from cr.ledger import K_EMPTY, Ledger, QuerySpec, RelativeRef, canonical_id, canonical_terms
from cr.models import Person

P = Person(full_name="Josiah Quill Tester", birth_year=1840)


def L(enabled=True):
    return Ledger(enabled=enabled, life_window=(1840, 1940), current_year=2026)


def q(**kw):
    base = dict(tool="ia_fts", terms='"Josiah Tester" regiment', lane="military")
    base.update(kw)
    return QuerySpec(**base)


def test_canonicalization():
    assert canonical_terms('Regiment "Josiah  Tester"') == canonical_terms('"josiah tester" REGIMENT.')
    assert canonical_id(q(terms='alpha beta "x y"')) == canonical_id(q(terms='"x y" beta, alpha'))
    assert canonical_id(q(terms="Mary St. Clair")) == canonical_id(q(terms="mary saint clair"))
    assert canonical_id(q(terms="José Tester")) == canonical_id(q(terms="Jose Tester"))
    assert canonical_id(q(terms="the Tester of town")) == canonical_id(q(terms="tester town"))
    # person_ref is not part of the id: two branches asking the same search for the same person collide
    assert canonical_id(q(person_ref="a")) == canonical_id(q(person_ref="b"))
    assert canonical_id(q(offset=0)) != canonical_id(q(offset=10))


def test_exact_repeat_blocked_and_not_charged():
    led = L()
    d1 = led.reserve(q(), "lane-a")
    assert d1.decision == "new" and len(led.s.entries) == 1
    d2 = led.reserve(q(terms='regiment "JOSIAH TESTER"'), "lane-b")
    assert d2.decision == "blocked_repeat" and not d2.allowed
    assert len(led.s.entries) == 1  # nothing reserved, so nothing charged
    assert led.s.log[-1]["decision"] == "blocked_repeat" and led.s.log[-1]["requested_by"] == "lane-b"


def test_near_repeat_blocked():
    led = L()
    led.reserve(q(terms="josiah tester regiment company volunteer infantry ohio enlisted 1862"), "a")
    d = led.reserve(q(terms="josiah tester regiment company volunteer infantry ohio enlisted 1862 private"), "b")
    assert d.decision in ("blocked_near", "blocked_no_key")
    assert not d.allowed


def test_revisit_keys_each_allowed_once_with_reason():
    led = L()
    book = dict(tool="ia_inside", collection_or_item="mockbook", lane="census")
    assert led.reserve(QuerySpec(terms="Josiah Tester", name_form="Josiah Tester", **book), "a").decision == "new"
    led.record(canonical_id(QuerySpec(terms="Josiah Tester", name_form="Josiah Tester", **book)), 3, 2, hit_pages=[40])
    # name variant: allowed once, then blocked
    d = led.reserve(QuerySpec(terms="J. Q. Tester", name_form="J. Q. Tester", **book), "a")
    assert d.decision == "revisit" and d.key_type == "name_variant" and d.reason
    d = led.reserve(QuerySpec(terms="J. Q. Tester", name_form="J. Q. Tester", **book), "b")
    assert not d.allowed
    # adjacent pages after the hit on page 40
    pg = dict(book, tool="ia_inside_pages")
    d = led.reserve(QuerySpec(terms="Tester", page_window=(41, 50), **pg), "a")
    assert d.key_type == "adjacent_pages" and "41-50" in d.reason and "page 40" in d.reason
    d = led.reserve(QuerySpec(terms="Tester", page_window=(45, 54), **pg), "a")
    assert not d.allowed  # overlaps a window already read
    d = led.reserve(QuerySpec(terms="Tester", page_window=(200, 209), **pg), "a")
    assert not d.allowed  # far from any hit
    # date window on a newspaper search
    led.reserve(q(tool="chronam", terms='"Josiah Tester"', date_window=(1860, 1869)), "n")
    d = led.reserve(q(tool="chronam", terms='"Josiah Tester"', date_window=(1870, 1879)), "n")
    assert d.key_type == "date_window" and d.reason
    d = led.reserve(q(tool="chronam", terms='"Josiah Tester"', date_window=(1865, 1874)), "n")
    assert not d.allowed
    d = led.reserve(q(tool="chronam", terms='"Josiah Tester"', date_window=(1990, 1999)), "n")
    assert not d.allowed  # outside the life window
    # result offset only after a page that matched
    cid0 = canonical_id(q())
    led.reserve(q(), "f")
    d = led.reserve(q(offset=10), "f")
    assert not d.allowed  # previous page not done yet
    led.record(cid0, 10, 1)
    d = led.reserve(q(offset=10), "f")
    assert d.key_type == "result_offset" and d.reason
    # different collection: same terms elsewhere
    d = led.reserve(q(collection_or_item="americana"), "f")
    assert d.key_type == "different_collection" and d.reason
    revisits = [r for r in led.s.log if r["decision"] == "revisit"]
    assert revisits and all(r.get("reason") for r in revisits)


def test_relative_name_refused_when_presumed_living():
    led = L()
    book = dict(tool="ia_inside", collection_or_item="mockbook", lane="land")
    led.reserve(QuerySpec(terms="Josiah Tester", name_form="Josiah Tester", **book), "a")
    spouse = RelativeRef(name="Ada Tester", relation="spouse")  # no dates: presumed living
    d = led.reserve(QuerySpec(terms="Ada Tester", relative=spouse, **book), "a")
    assert d.decision == "refused_living" and not d.allowed
    parent = RelativeRef(name="Amos Tester", relation="parent", birth_year=1828, birth_year_precision="before")
    d = led.reserve(QuerySpec(terms="Amos Tester", relative=parent, **book), "a")
    assert d.decision == "revisit" and d.key_type == "relative_name"


def test_foraging_stop_after_k_empties():
    led = L()
    book = dict(tool="ia_inside", collection_or_item="drybook", lane="census")
    forms = ["Josiah Tester", "J. Tester", "J. Q. Tester", "Josiah Q. Tester"]
    for f in forms[:K_EMPTY]:
        d = led.reserve(QuerySpec(terms=f, name_form=f, **book), "a")
        assert d.allowed
        led.record(d.canonical_id, 0, 0)
    d = led.reserve(QuerySpec(terms=forms[K_EMPTY], name_form=forms[K_EMPTY], **book), "a")
    assert d.decision == "blocked_closed"
    parent = RelativeRef(name="Amos Tester", relation="parent", birth_year=1828, birth_year_precision="before")
    d = led.reserve(QuerySpec(terms="Amos Tester", relative=parent, **book), "a")
    assert d.allowed  # a new verified relative key reopens it


def test_suggest_returns_only_allowed_specs():
    led = L()
    sp = q(name_form="Josiah Tester")
    d = led.reserve(sp, "a")
    led.record(d.canonical_id, 5, 1)
    out = led.suggest(sp, P)
    assert 0 < len(out) <= 3
    for spec, dec in out:
        assert dec.allowed
        assert led.classify(spec).allowed


def test_no_ledger_mode_allows_repeats_but_logs():
    led = L(enabled=False)
    assert led.reserve(q(), "a").allowed
    assert led.reserve(q(), "b").allowed
    assert [r["decision"] for r in led.s.log] == ["unchecked", "unchecked"]
