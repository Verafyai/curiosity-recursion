"""Living-person gate (cr/gate.py), a port of kin lib/gate.ts. Unknown defaults to living."""
from cr.gate import MAX_PLAUSIBLE_AGE, gate, is_presumed_living
from cr.models import Person

YEAR = 2026


def test_unknown_dates_mean_living():
    assert is_presumed_living(Person(full_name="No Dates"), YEAR)


def test_death_on_record_is_not_living():
    assert not is_presumed_living(Person(full_name="Erastus W. Burnham", birth_year=1834, death_year=1921), YEAR)


def test_death_after_precision_does_not_count():
    assert is_presumed_living(Person(full_name="X", birth_year=1950, death_year=2000, death_year_precision="after"), YEAR)


def test_birth_at_least_110_years_ago():
    assert not is_presumed_living(Person(full_name="X", birth_year=YEAR - MAX_PLAUSIBLE_AGE), YEAR)
    assert is_presumed_living(Person(full_name="X", birth_year=YEAR - MAX_PLAUSIBLE_AGE + 1), YEAR)


def test_born_1950_is_blocked_with_reason():
    g = gate(Person(full_name="Jane Example", birth_year=1950), YEAR)
    assert not g.allowed and "presumed living" in g.reason
