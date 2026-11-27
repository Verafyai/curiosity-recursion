"""Outline-first planning from several viewpoints (spec section 4).

STORM (`shao2024storm`) and Co-STORM (`jiang2024costorm`) plan an article from several perspectives
before searching; Anthropic's research system (`anthropic2025multiagent`) gives each worker an
objective, its tools, an output format and explicit boundaries so workers do not duplicate each
other. `plan_outline()` builds that plan as a grid of lanes (viewpoint x record type x date window)
from the input card alone (name plus birth year): deterministic, no model, no network.

Lanes whose record types are offline become stubs: a drafted request to the institution that holds
them (never sent), so they can still earn the 0.5 named-archive credit.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from cr.ledger import QuerySpec, life_window
from cr.models import Person
from cr.variants import split_name

SECTIONS = ("birth", "marriage", "children", "residence", "occupation", "service", "death", "burial")
WARS = (("Civil War", 1861, 1865), ("Spanish-American War", 1898, 1898), ("World War I", 1917, 1918), ("World War II", 1941, 1945),
        ("Korean War", 1950, 1953), ("Vietnam War", 1964, 1973))
CHRONAM_LAST_YEAR = 1963  # Chronicling America coverage ends here


class Stub(BaseModel):
    to: str
    record_type: str
    why: str
    contact_hint: str


class Lane(BaseModel):
    id: str
    viewpoint: str
    record_types: list[str]
    date_window: Optional[tuple[int, int]] = None
    objective: str
    tools: list[str]
    boundaries: str
    sections: list[str]
    prior: float = Field(description="Era prior weight in [0, 1]; the allocator's starting value")
    seeds: list[QuerySpec] = Field(default_factory=list)
    stubs: list[Stub] = Field(default_factory=list)


class Outline(BaseModel):
    era: str
    wars: list[str]
    life_window: tuple[int, int]
    lanes: list[Lane]
    coverage: dict[str, str] = Field(default_factory=lambda: {s: "missing" for s in SECTIONS})


def wars_for(p: Person) -> list[tuple[str, int, int]]:
    """Wars the subject could have served in (age 17 to 45 at some point of the war)."""
    if not p.birth_year:
        return []
    return [(w, a, b) for w, a, b in WARS if a - p.birth_year <= 45 and b - p.birth_year >= 17]


def era_of(p: Person) -> str:
    w = wars_for(p)
    return w[0][0] if w else "civilian"


def _q(name: str) -> str:
    return f'"{name}"'


def plan_outline(p: Person, reflections: list[str] | None = None, tools: str = "v2") -> Outline:
    lo, hi = life_window(p)
    given, sur = split_name(p.full_name)
    full = p.full_name
    short = f"{given[0]} {sur}" if given and sur else full
    wars = wars_for(p)
    fts = "ia_fts" if tools == "v2" else "ia_fulltext"
    mil = 0.9 if wars else 0.2
    civ = 0.6 if wars else 0.8

    def s(tool, terms, lane, section, purpose, **kw):
        return QuerySpec(tool=tool, terms=terms, lane=lane, section=section, purpose=purpose,
                         grounding=f"outline cell {lane}/{section} (input card: {full}, born {p.birth_year})", **kw)

    lanes: list[Lane] = []
    lanes.append(Lane(
        id="reference", viewpoint="reference", record_types=["Wikidata person items"], objective=f"Find a structured identity item for {full}.",
        tools=["wikidata_search", "wikidata_entities"], boundaries="Only Wikidata; books and newspapers belong to other lanes.",
        sections=["birth", "death"], prior=0.3,
        seeds=[s("wikidata_search", n, "reference", "birth", f"Is there a Wikidata item for {n}?", name_form=n) for n in dict.fromkeys([full, short])]))
    if wars:
        war_terms = [w for w, _, _ in wars]
        seeds = [s(fts, f'{_q(full)} regiment', "military", "service", f"Which unit did {full} serve in?", name_form=full),
                 s(fts, f'{_q(short)} {war_terms[0]}', "military", "service", f"Is {short} named in a {war_terms[0]} book?", name_form=short),
                 s("ia_title", f"{sur} {war_terms[0]} roster", "military", "service", f"Which rosters for the {war_terms[0]} might list {sur}?")]
        seeds += [s(fts, f'{_q(short)} enlisted', "military", "service", f"When did {short} enlist?", name_form=short)]
        lanes.append(Lane(
            id="military", viewpoint="military", record_types=["unit histories", "regimental rosters", "pension indexes", "adjutant general reports", "veterans' posts"],
            date_window=(wars[0][1], wars[-1][2]), objective=f"Find service records for {full} in the {', '.join(war_terms)}.",
            tools=[fts, "ia_inside", "ia_inside_pages", "ia_title"], boundaries="Books only; do not search newspapers (newspaper lanes do) or Wikidata.",
            sections=["service"], prior=mil, seeds=seeds,
            stubs=[Stub(to="National Archives and Records Administration (NARA), Washington, DC", record_type="military service and pension files",
                        why="Compiled service records and pension files are not keyless online sources.",
                        contact_hint="Order through archives.gov; check current fees there; nothing is filled in here.")]))
    lanes.append(Lane(
        id="census", viewpoint="census", record_types=["federal and state census households", "city directories"],
        objective=f"Find households and directory entries for {full}.", tools=[fts, "ia_inside", "ia_inside_pages"],
        boundaries="Directories and census transcriptions in books; no newspapers, no Wikidata.", sections=["residence", "occupation"], prior=civ,
        seeds=[s(fts, f'{_q(full)}', "census", "residence", f"Which books print the full name {full}?", name_form=full),
               s(fts, f'{_q(short)} directory', "census", "occupation", f"Is {short} in a city directory?", name_form=short),
               s(fts, f'{_q(short)}', "census", "residence", f"Which books print {short}?", name_form=short, collection_or_item="allen_county")]))
    lanes.append(Lane(
        id="church", viewpoint="church", record_types=["parish and congregational registers", "church histories", "cemetery and burial lists"],
        objective=f"Find baptism, marriage and burial entries for {full}.", tools=[fts, "ia_inside", "ia_inside_pages"],
        boundaries="Church and cemetery books only; no newspapers, no Wikidata.", sections=["birth", "marriage", "burial"], prior=civ * 0.9,
        seeds=[s(fts, f'{_q(short)} married', "church", "marriage", f"Where and when did {short} marry?", name_form=short),
               s(fts, f'{_q(short)} church', "church", "marriage", f"Which church records name {short}?", name_form=short),
               s(fts, f'{_q(short)} cemetery', "church", "burial", f"Where is {short} buried?", name_form=short)],
        stubs=[Stub(to="FamilySearch Library catalog (search by place, then church records)", record_type="church registers",
                    why="Parish registers for a known town are usually offline or behind sign-in; the catalog names where the films are held.",
                    contact_hint="Search the FamilySearch Library catalog by place; nothing is fetched here.")]))
    # newspapers: one lane per life phase, Chronicling America ends in 1963
    phases = [("young", lo + 15, lo + 39, ["marriage", "residence"]), ("middle", lo + 40, lo + 64, ["residence", "occupation", "children"]),
              ("late", lo + 65, min(hi, lo + 100), ["death", "burial"])]
    for name, a, b, secs in phases:
        b = min(b, CHRONAM_LAST_YEAR)
        if a > b:
            continue
        mid = a + (b - a) // 2
        lanes.append(Lane(
            id=f"newspaper-{name}", viewpoint="newspaper", record_types=["obituaries", "marriage and birth notices", "local items"], date_window=(a, b),
            objective=f"Find newspaper items naming {full} between {a} and {b}.", tools=["chronam"],
            boundaries=f"Chronicling America only, dates {a} to {b}; other date windows belong to the other newspaper lanes.",
            sections=secs, prior=civ * 0.8,
            seeds=[s("chronam", _q(full), f"newspaper-{name}", secs[0], f"Do newspapers {a} to {mid} print {full}?", name_form=full, date_window=(a, mid)),
                   s("chronam", _q(short), f"newspaper-{name}", secs[-1], f"Do newspapers {mid + 1} to {b} print {short}?", name_form=short, date_window=(mid + 1, b))]))
    lanes.append(Lane(
        id="land", viewpoint="land", record_types=["deeds", "county atlases and plat books", "town and county histories", "family genealogies"],
        objective=f"Find {full} in county histories and family genealogies.", tools=[fts, "ia_title", "ia_inside", "ia_inside_pages"],
        boundaries="County histories and genealogies; no newspapers, no Wikidata.", sections=["residence", "children", "birth"], prior=civ,
        seeds=[s("ia_title", f"{sur} genealogy", "land", "children", f"Which family genealogies cover the {sur} family?"),
               s(fts, f'{_q(short)} county history', "land", "residence", f"Which county histories name {short}?", name_form=short),
               s(fts, f'{_q(full)} born', "land", "birth", f"Which books give the birth of {full}?", name_form=full)],
        stubs=[Stub(to="FamilySearch Library catalog (search by place, then land records)", record_type="deeds and land records",
                    why="County deed books are offline for most places and periods.", contact_hint="Search the FamilySearch Library catalog by place; nothing is fetched here.")]))
    lanes.append(Lane(
        id="probate", viewpoint="probate", record_types=["wills", "estate notices", "guardianship", "court records"],
        objective=f"Find wills and estate notices for {full}.", tools=[fts, "ia_inside", "ia_inside_pages"],
        boundaries="Probate and court books only; no newspapers, no Wikidata.", sections=["death", "children"], prior=civ * 0.6,
        seeds=[s(fts, f'{_q(short)} estate', "probate", "death", f"Is there an estate notice for {short}?", name_form=short),
               s(fts, f'{_q(short)} deceased', "probate", "death", f"Which records name {short} as deceased?", name_form=short)],
        stubs=[Stub(to="FamilySearch Library catalog (search by place, then probate records)", record_type="probate and estate files",
                    why="Probate files are held by county courts and are rarely online.", contact_hint="Search the FamilySearch Library catalog by place; nothing is fetched here."),
               Stub(to="County probate court clerk, the county where they died", record_type="probate files", why="The court holds the original file.",
                    contact_hint="Use the court's official website for the mailing address.")]))
    lanes.append(Lane(
        id="immigration", viewpoint="immigration", record_types=["passenger lists", "naturalization indexes", "ethnic society histories"],
        objective=f"Find arrival or naturalization records for {full}.", tools=[fts, "ia_inside", "ia_inside_pages"],
        boundaries="Immigration books only; no newspapers, no Wikidata.", sections=["birth", "residence"], prior=0.3,
        seeds=[s(fts, f'{_q(short)} naturalized', "immigration", "residence", f"Was {short} naturalized?", name_form=short)]))
    return Outline(era=era_of(p), wars=[w for w, _, _ in wars], life_window=(lo, hi), lanes=lanes)
