"""Name variants are deterministic and local (synthetic names only, never benchmark people)."""
from cr.variants import nysiis, phonetic_key, soundex, variants


def test_deterministic_variant_sets():
    a = variants("Josiah Quill Tester")
    assert a == variants("Josiah Quill Tester")
    assert "Josiah Q. Tester" in a and "J. Q. Tester" in a and "J. Tester" in a
    assert "Josiah Quill Tester" not in a
    assert len(a) == len(set(x.lower() for x in a))


def test_saint_forms_and_abbreviations():
    v = variants("Mary St. Clair")
    assert "Mary Saint Clair" in v and "Mary St Clair" in v
    assert "Wm. Sample" in variants("William Sample")


def test_phonetic_keys():
    assert soundex("Robert") == "R163" and soundex("Rupert") == "R163"
    assert soundex("Tymczak") == "T522"
    assert nysiis("Knight") == nysiis("Night")
    assert phonetic_key("Josiah Tester") == phonetic_key("Josiah Tesster")
