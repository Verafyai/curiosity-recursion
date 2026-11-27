"""Research circuits: topics (what a finished Studio output needs) and the steps that can fill them.

Stage numbers are kin's run-pass STAGE_LABELS (lib/search/run-pass.ts):
1 identity resolution, 2 vital records, 3 place and migration, 4 kin graph,
5 military service, 6 local holdings, 7 lineage assembly.

Templates are kin's Studio TEMPLATES (lib/content/studio.ts): service-record,
the-crossing, book-of-daniel. In kin only book-of-daniel is live; here each circuit
picks the template that matches it.

Each topic lists steps in the order the supervisor should try them. Round 1 runs
the circuit's `opening` steps (a shallow first pass, like a first prompt). After
that the gap-analysis activity decides where to dig next.
"""

from __future__ import annotations

from pydantic import BaseModel

from studio.models import StepSpec

STAGE_LABELS = [
    "",
    "identity resolution",
    "vital records",
    "place and migration",
    "kin graph",
    "military service",
    "local holdings",
    "lineage assembly",
]


class Topic(BaseModel):
    id: str
    label: str
    fields: list[str]
    keywords: list[str]
    steps: list[str]
    candidate_counts: bool = True  # do name-match leads count as "leads_only"?


class Circuit(BaseModel):
    id: str
    title: str
    template: str
    blurb: str
    opening: list[str]
    topics: list[Topic]


def S(id, title, stage, slug, mode, handler, topic, fields=(), query="", why_stub="", flaky=False) -> StepSpec:
    return StepSpec(
        id=id, title=title, stage=stage, source_slug=slug, mode=mode, handler=handler, topic=topic,
        fixture_fields=list(fields), query=query, why_stub=why_stub, flaky=flaky,
    )


NO_FIXTURE_LOOKUP = "No free, keyless API for this record set; this step reads the Lineage eval fixture only."

STEPS: dict[str, StepSpec] = {s.id: s for s in [
    # stage 1
    S("wikidata_identity", "Wikidata people search", 1, "wikidata", "live", "wikidata", "identity"),
    # stage 2 vital records
    S("vital_birth", "Birth record", 2, "none", "stub", "fixture", "birth", ["birth"],
      why_stub="State vital records are not in the live catalog (letter or paid). " + NO_FIXTURE_LOOKUP),
    S("vital_marriage", "Marriage record", 2, "none", "stub", "fixture", "marriage", ["marriage"],
      why_stub="Marriage registers are county-held. " + NO_FIXTURE_LOOKUP),
    S("vital_death", "Death record", 2, "none", "stub", "fixture", "death", ["death"],
      why_stub="Death registers are state-held. " + NO_FIXTURE_LOOKUP),
    S("findagrave_link", "Find a Grave memorial (link only)", 2, "none", "stub", "findagrave", "burial",
      why_stub="Find a Grave is not in the catalog and its terms prohibit automated access. Lineage keeps ids and links only."),
    S("census_households", "Census households", 2, "us-census-1950", "stub", "fixture", "census", ["residence"],
      why_stub="The live catalog has the 1950 census only. Earlier enumerations come from the eval fixture.", flaky=True),
    S("chronam_obituary", "Newspapers: obituary and notices", 2, "loc-chronicling-america", "live", "chronam", "burial",
      query="{name}"),
    # stage 3 place and migration
    S("passenger_manifests", "Passenger manifests", 3, "none", "stub", "fixture", "passage", ["immigration", "arrival"],
      why_stub="Arrival manifests sit behind FamilySearch login or Ancestry; not in the keyless catalog."),
    S("naturalization", "Naturalization papers", 3, "us-national-archives", "stub", "fixture", "naturalization", ["naturalization"],
      why_stub="The NARA catalog API now needs a key. Not called here."),
    S("ia_place_history", "Town and county histories", 3, "internet-archive", "live", "ia", "place",
      query='title:(history) AND ("{town}")'),
    S("photos", "Photographs in local collections", 6, "none", "stub", "relatives_photos", "photos",
      why_stub="Wood Memorial PastPerfect pages are out of reach for automated fetch; titles come from the relatives fixture."),
    # stage 4 kin graph
    S("kin_parents", "Parents (birth and census records)", 4, "none", "stub", "fixture", "parents", ["parent", "father", "mother"],
      why_stub=NO_FIXTURE_LOOKUP),
    S("wikitree_kin", "WikiTree / Wikidata relatives", 4, "wikidata", "live", "wikidata_kin", "parents"),
    S("kin_children", "Children", 4, "none", "stub", "fixture", "children", ["child"], why_stub=NO_FIXTURE_LOOKUP),
    # stage 5 military
    S("service_roster", "State roster: Record of Service", 5, "internet-archive", "stub", "fixture", "unit", ["military"],
      why_stub="The roster volumes are on Internet Archive, but reading the right page needs a paid Lineage run. Claims come from the eval fixture."),
    S("ia_regimental", "Regimental histories", 5, "internet-archive", "live", "ia", "unit",
      query='title:(regiment) AND title:("{state}") AND title:(volunteer OR rebellion)'),
    S("nps_soldiers", "NPS Soldiers and Sailors database", 5, "none", "stub", "relatives_sources", "unit",
      query="NPS Soldiers and Sailors", why_stub="NPS has no public API; ids come from the relatives fixture."),
    S("pension_index", "Pension index (NARA T288)", 5, "familysearch", "stub", "fixture", "pension", ["pension"],
      why_stub="FamilySearch is user_oauth in the catalog: needs the user's own login. Not called."),
    # stage 6 local holdings
    S("chronam_name", "Newspapers: name search", 6, "loc-chronicling-america", "live", "chronam", "newspapers",
      query="{name}"),
    S("occupation_records", "Work, school and directories", 6, "none", "stub", "fixture", "work",
      ["occupation", "education", "membership"], why_stub=NO_FIXTURE_LOOKUP),
]}

T = Topic

CIRCUITS: dict[str, Circuit] = {c.id: c for c in [
    Circuit(
        id="civil_war_veteran",
        title="Civil War veteran",
        template="service-record",
        blurb="Unit, enlistment and discharge, pension, burial, and the household before and after.",
        opening=["wikidata_identity", "ia_regimental"],
        topics=[
            T(id="unit", label="Unit and service dates", fields=["military"], keywords=["unit", "regiment", "serve", "service", "enlist", "war"],
              steps=["service_roster", "nps_soldiers", "ia_regimental"]),
            T(id="burial", label="Burial", fields=["burial", "death"], keywords=["buried", "burial", "grave", "cemetery", "died", "death"],
              steps=["vital_death", "findagrave_link", "chronam_obituary"]),
            T(id="pension", label="Pension file", fields=["pension"], keywords=["pension"], steps=["pension_index"]),
            T(id="census", label="Census households", fields=["residence"], keywords=["census", "lived", "household"],
              steps=["census_households", "ia_place_history"]),
            T(id="birth", label="Birth", fields=["birth"], keywords=["born", "birth"], steps=["vital_birth"]),
            T(id="marriage", label="Marriage", fields=["marriage"], keywords=["married", "wife", "spouse"], steps=["vital_marriage"]),
            T(id="parents", label="Parents", fields=["parent", "father", "mother"], keywords=["parents", "father", "mother"],
              steps=["kin_parents", "wikitree_kin"]),
            T(id="work", label="Work before and after the war", fields=["occupation", "education", "membership"],
              keywords=["work", "job", "occupation", "whal"], steps=["occupation_records", "chronam_name"]),
        ],
    ),
    Circuit(
        id="the_crossing",
        title="The crossing (immigration)",
        template="the-crossing",
        blurb="Where they came from, the passage, naturalisation, and the household they settled into.",
        opening=["wikidata_identity", "chronam_name"],
        topics=[
            T(id="origin", label="Birthplace abroad", fields=["birth"], keywords=["born", "from", "origin", "came"], steps=["vital_birth"]),
            T(id="passage", label="Passage and arrival", fields=["immigration", "arrival"], keywords=["arriv", "ship", "crossing", "emigrat", "immigrat"],
              steps=["passenger_manifests"]),
            T(id="naturalization", label="Naturalisation", fields=["naturalization"], keywords=["natural", "citizen"], steps=["naturalization"]),
            T(id="marriage", label="Marriage", fields=["marriage"], keywords=["married", "husband", "wife"], steps=["vital_marriage"]),
            T(id="settling", label="Where they settled", fields=["residence"], keywords=["settle", "lived", "census"],
              steps=["census_households", "ia_place_history"]),
            T(id="photos", label="Photographs", fields=["photo"], keywords=["photo", "picture"], steps=["photos"]),
            T(id="burial", label="Death and burial", fields=["death", "burial"], keywords=["died", "buried", "death"],
              steps=["vital_death", "findagrave_link", "chronam_obituary"]),
            T(id="parents", label="Parents", fields=["parent", "father", "mother"], keywords=["parents", "father", "mother"],
              steps=["kin_parents", "wikitree_kin"]),
        ],
    ),
    Circuit(
        id="vital_records",
        title="Vital records life story",
        template="book-of-daniel",
        blurb="Birth, marriage, death and burial, census decades, work and family, told in order.",
        opening=["wikidata_identity", "chronam_name"],
        topics=[
            T(id="birth", label="Birth", fields=["birth"], keywords=["born", "birth"], steps=["vital_birth"]),
            T(id="marriage", label="Marriage", fields=["marriage"], keywords=["married", "wife", "husband"], steps=["vital_marriage"]),
            T(id="work", label="Work and schooling", fields=["occupation", "education", "membership"], keywords=["work", "job", "school", "occupation"],
              steps=["occupation_records"]),
            T(id="census", label="Census and addresses", fields=["residence"], keywords=["census", "lived", "address"],
              steps=["census_households", "ia_place_history"]),
            T(id="children", label="Children", fields=["child"], keywords=["children", "son", "daughter"], steps=["kin_children"]),
            T(id="burial", label="Death and burial", fields=["death", "burial"], keywords=["died", "buried", "death"],
              steps=["vital_death", "findagrave_link", "chronam_obituary"]),
            T(id="parents", label="Parents", fields=["parent", "father", "mother"], keywords=["parents", "father", "mother"],
              steps=["kin_parents", "wikitree_kin"]),
        ],
    ),
]}


def circuit_for(circuit_id: str) -> Circuit:
    return CIRCUITS[circuit_id]
