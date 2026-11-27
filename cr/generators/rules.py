"""The brainstorm: read every finding so far and ask new questions.

This is the automated version of "keep going, look over here, what about the
ship, which books cover that regiment, did you check the church". Rule-based
lead templates keyed on what a finding contains:

  military unit  -> which books cover the unit? newspapers on the unit?
  ship / voyage  -> which voyages, crew lists, logbooks?
  place          -> which church served the town? school records? town histories?
  marriage place -> church or town marriage register?
  school         -> registers, catalogues, yearbooks?
  church/society -> its own bulletins and records?
  death year     -> obituary that year?
  any book hit   -> does that book name him, and on which page?
  snippet 'son of A and B' -> who were A and B? (and then their parents...)
  snippet 'X Collection'   -> what is in that collection? (stub: letter only)
  checklist gap  -> say plainly what is still missing and why it is stubbed

Every question carries the finding that sparked it, so the tree is auditable.
Pure and deterministic. It runs inside an activity, so cr/generators/llm.py can stand in
for it without touching workflow code. Every candidate must name its spark (`grounded()`);
ungrounded candidates are counted and dropped.
"""

from __future__ import annotations

import re

from cr.circuits import CIRCUITS, STEPS
from cr.models import (
    BrainstormInput, BrainstormOutput, Citation, Claim, Finding, Gap, Person, Plan, Question, ResearchRequest,
)
from cr.models import grounded
from cr.names import ORD, WORD2NUM, given, match, surname, town_state
from cr.novelty import canonical_key

STATES = ("Connecticut|Massachusetts|New York|New Hampshire|Vermont|Maine|Rhode Island|New Jersey|Pennsylvania|Ohio|"
          "Indiana|Illinois|Michigan|Wisconsin|Iowa|Minnesota|Kentucky|Tennessee|Virginia|Maryland|Delaware|Missouri|Kansas")
UNIT_NUM = re.compile(rf"\b(\d{{1,3}})(?:st|nd|rd|th)\s+(?:Regiment,?\s+)?({STATES})\s+(?:Volunteer\s+)?(Heavy Artillery|Infantry|Cavalry|Artillery)", re.I)
UNIT_WORD = re.compile(rf"\b({'|'.join(ORD.values())})\s+(?:Regt\.?|Regiment|C\.\s*V\.)\s*,?\s*({STATES})\s*(Heavy Artillery|Infantry|Cavalry|Artillery|Volunteers?)?", re.I)
SHIP = re.compile(r"\b(whaleship|whale ship|ship|bark|barque|brig|schooner)\s+([A-Z][a-z]+)(?:\s+of\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?))?")
PARENTS = re.compile(r"\b(?:son|daughter|dau\.?)\s+of\s+([A-Z][a-z]+(?:\s[A-Z]\.)?)\s+and\s+([A-Z][a-z]+)(?:\s*\(([A-Z][a-z]+)\))?")
COLLECTION = re.compile(r"((?:[A-Z][a-z]+\s){1,4}(?:Library|Museum|Society|Historical Society))\b[^.]{0,60}?\bCollection")
MARRIAGE_PLACE = re.compile(r"\b(1[6-9]\d\d),\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")
SCHOOL = re.compile(r"\b(College of (?:the )?[A-Z][A-Za-z]+(?: (?:of|the|[A-Z][a-z]+))*|[A-Z][a-z]+ University|University of [A-Z][a-z]+)")
ORG = re.compile(r"\b((?:[A-Z][a-z]+\s){1,3}(?:Jewish Center|Church|Synagogue|Temple|Lodge|Grange|Post))\b")
RESIDENCE = re.compile(r"\b(?:residence|Residence|lived in|Lived in)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)")


_key = canonical_key  # kappa(q) in the paper


def _texts(findings: list[Finding]) -> list[tuple[str, str, Finding, Citation | None, Claim | None]]:
    """(text, ref, finding, citation, claim) for every claim and snippet seen."""
    out = []
    for f in findings:
        for c in f.claims:
            out.append((c.text, c.id, f, c.citation, c))
        for cit in f.citations:
            if cit.snippet:
                out.append((cit.snippet.replace("**", ""), cit.url or cit.title, f, cit, None))
    return out


def _years(p: Person) -> tuple[int, int] | None:
    if p.birth_year and p.death_year:
        return (p.birth_year, p.death_year + 1)
    if p.birth_year:
        return (p.birth_year, p.birth_year + 90)
    return None


def checklist(req: ResearchRequest, findings: list[Finding]) -> list[Gap]:
    circuit = CIRCUITS[req.circuit_id]
    q = req.question.lower()
    gaps = []
    for t in circuit.topics:
        claims = [c for f in findings if f.about is None for c in f.claims if c.field in t.fields]
        leads = [f for f in findings if f.about is None and STEPS.get(f.step_id) and STEPS[f.step_id].topic == t.id and f.citations]
        state = "covered" if claims else ("leads_only" if leads else "missing")
        ev = claims[0].text if claims else (leads[0].citations[0].title if leads else "")
        gaps.append(Gap(topic=t.id, label=t.label, state=state, asked=any(k in q for k in t.keywords), evidence=ev[:160]))
    return gaps


YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")


def _in_life(p: Person, text: str, year: int | None = None) -> bool:
    """v2 life-window check: a snippet whose years all fall outside the subject's life (plus 40 years
    for obituaries, estates and family histories) is probably about someone else of the same name."""
    lo = (p.birth_year or 0) - 1
    hi = (p.death_year or ((p.birth_year or 0) + 100)) + 40
    if year and p.birth_year and year < p.birth_year + 12:
        return False  # printed before he could appear in it as an adult
    ys = [int(y) for y in YEAR.findall(text or "")]
    return not ys or any(lo <= y <= hi for y in ys)


PARTICLES = {"st", "saint", "ste", "van", "von", "de", "del", "della", "la", "le", "du", "da", "di", "mac", "o"}


def surname2(p: Person) -> str:
    """v2: keep surname particles, so "Homer Doble St. John" has surname "St. John", not "John"."""
    parts = p.full_name.split()
    parts = [x for x in parts if x.lower().strip(".,") not in ("jr", "sr", "ii", "iii")]
    if len(parts) >= 3 and parts[-2].lower().strip(".") in PARTICLES:
        return " ".join(parts[-2:])
    return parts[-1] if parts else ""


def _forms(p: Person) -> list[str]:
    """v2: the standard ways a record prints a name, built from the card alone: given plus surname,
    given plus middle initial, initials, and Saint spelled out. Records rarely print a full middle name."""
    s = surname2(p)
    rest = p.full_name[: len(p.full_name) - len(s)].split() if s and p.full_name.endswith(s) else p.full_name.split()[:-1]
    rest = [x for x in rest if x.lower().strip(".,") not in ("jr", "sr")]
    if not rest or not s:
        return []
    g, mids = rest[0], rest[1:]
    out = [f"{g} {s}"]
    if mids:
        out += [f"{g} {mids[0][0]}. {s}", f"{g[0]}. {mids[0][0]}. {s}"]
    if s.lower().startswith("st. ") or s.lower().startswith("st "):
        out.append(f"{g} Saint {s.split(None, 1)[1]}")
    seen = {n.lower() for n in p.all_names()}
    return [x for x in out if x.lower() not in seen]


def _variants(p: Person, findings: list[Finding]) -> list[str]:
    """v2: name forms seen in strong, in-life snippets ("Erastus W. Burnham", "E. W. Burnham")."""
    g, s = given(p), surname2(p)
    if not g or not s:
        return []
    out: list[str] = []
    pat = re.compile(rf"\b({re.escape(g)}\s+[A-Z]\.?\s+(?:[A-Z]\.?\s+)?{re.escape(s)}|{g[0]}\.\s*[A-Z]\.\s*{re.escape(s)})\b")
    for f in findings:
        if f.about is not None:
            continue
        for c in f.citations:
            sn = (c.snippet or "").replace("**", "")
            if not sn or not _in_life(p, sn, c.year):
                continue
            for m in pat.finditer(sn):
                v = re.sub(r"\s+", " ", m.group(1)).strip()
                if v.lower() not in [x.lower() for x in out + p.all_names()]:
                    out.append(v)
    return out[:4]


def _windows(p: Person) -> list[tuple[int, int]]:
    """v2: newspaper windows over the adult life, 15 years each, inside Chronicling America's range."""
    if not p.birth_year:
        return []
    a, z = p.birth_year + 15, min((p.death_year or p.birth_year + 85) + 1, 1963)
    out = []
    while a <= z:
        out.append((a, min(a + 14, z)))
        a += 15
    return out


def brainstorm(inp: BrainstormInput, v2: bool = False) -> BrainstormOutput:
    req, p = inp.request, inp.request.person
    sname, gname = (surname2(p) if v2 else surname(p)), given(p)
    home_town, home_state = town_state(p.birth_place or p.death_place)
    asked = {q.key for q in inp.questions}
    qwords = req.question.lower()
    ideas: list[Question] = []
    n = 0

    def add(key, text, because, template, plan, score, parent=None, parent_q=None, about=None, bonus_words=()):
        nonlocal n
        if any(w in qwords for w in bonus_words):
            score += 2
        n += 1
        ideas.append(Question(
            id=f"q{inp.round}.{n}", key=key, round=inp.round, text=text, because=because, template=template,
            parent_finding=parent, parent_question=parent_q, about=about, score=score, plan=plan,
            mode="stub" if plan.handler == "stub" else "live",
        ))

    node = inp.node
    # 1. Mentions in books: the opener once the checklist has run.
    names = sorted(p.all_names(), key=lambda s: (-len(s.split()), -len(s)))
    for nm in (names[:2] if node is None else []):
        add(_key("fulltext", nm), f"Is \"{nm}\" mentioned by name in any digitised book?",
            "because the checklist round is done and books often hold what indexes miss", "name->books",
            Plan(handler="ia_fulltext", query=f'"{nm}"'), 9 if nm == names[0] else 5, parent="checklist:level-0",
            bonus_words=("book", "mention"))
    if v2 and node is None:
        # "Keep going" openers: other spellings, the home town, every stretch of his adult life in newspapers,
        # the obituary, and the town's own histories. Each is grounded in the subject card itself.
        for vn in (_forms(p) + [v for v in _variants(p, inp.findings) if v not in _forms(p)])[:6]:
            add(_key("fulltext", vn), f"Is he in books as \"{vn}\"?", f"because a snippet in his lifetime spells him \"{vn}\"",
                "variant->books", Plan(handler="ia_fulltext", query=f'"{vn}"'), 8, parent="card:name")
            add(_key("variant-news", vn), f"Do newspapers print \"{vn}\"?", f"because a snippet in his lifetime spells him \"{vn}\"",
                "variant->newspapers", Plan(handler="chronam", query=f'"{vn}"', years=_years(p)), 7, parent="card:name")
        if home_town:
            add(_key("town-books", sname, home_town), f"Which books name a {sname} of {home_town}?",
                f"because the card says he was born in {p.birth_place}", "place->books",
                Plan(handler="ia_fulltext", query=f'"{sname}" "{home_town}"'), 7, parent="card:birth_place")
            add(_key("town-history", home_town), f"Do the histories and vital records of {home_town} name him?",
                f"because the card says he was born in {p.birth_place}", "place->town-history",
                Plan(handler="ia_title", query=f'title:("{home_town}") AND title:(history OR genealogy OR genealogies OR vital OR records)'),
                6, parent="card:birth_place")
        for (a_, z_) in _windows(p):
            add(_key("life-news", sname, str(a_)), f"Was {gname} {sname} in a newspaper between {a_} and {z_}?",
                f"because the card puts his adult life across {a_} to {z_}", "life->newspapers",
                Plan(handler="chronam", query=f'"{gname} {sname}"', years=(a_, z_)), 5, parent="card:years")
        if p.death_year and p.death_year <= 1963:
            add(_key("obit", sname, str(p.death_year)), f"Was there an obituary for him in {p.death_year}?",
                f"because the card says he died in {p.death_year}", "death->obituary",
                Plan(handler="chronam", query=f"{sname} {home_town}".strip(), years=(p.death_year, p.death_year + 1)), 6, parent="card:death_year")

    for text, ref, f, cit, claim in _texts(inp.findings):
        about = f.about  # None = the subject
        who = about or p.full_name
        target = Person(full_name=who)
        strong = cit is None or cit.name_match in (None, "strong") or (cit.snippet and match(target, cit.snippet) == "strong")
        if not strong:
            continue
        if v2 and about is None and not _in_life(p, text, getattr(cit, "year", None) if cit else None):
            continue  # v2: probably a namesake from another century
        short = text[:110]
        qid = f.step_id if f.step_id.startswith("q") else None

        for m in list(UNIT_NUM.finditer(text)) + list(UNIT_WORD.finditer(text)):
            num = int(m.group(1)) if m.group(1).isdigit() else WORD2NUM.get(m.group(1).lower(), 0)
            state = m.group(2).title()
            arm = (m.group(3) or "").title().replace("Volunteers", "Infantry").replace("Volunteer", "Infantry") or "Infantry"
            if not num:
                continue
            unit = f"{num}{'th' if 10 <= num % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(num % 10, 'th')} {state} {arm}"
            word = ORD.get(num, str(num))
            add(_key("unit-books", unit), f"Which books cover the {unit}, and do they name him?",
                f"because {ref_label(ref, claim)} says \"{short}\"", "unit->books",
                Plan(handler="ia_title", query=f'title:({word} OR "{unit.split()[0]}") AND title:("{state}") AND title:(regiment OR artillery OR infantry OR cavalry OR volunteers) AND year:[1862 TO 1930]'),
                6, parent=ref, parent_q=qid, about=about, bonus_words=("unit", "regiment", "serve", "war"))
            add(_key("unit-news", unit, sname), f"Did a newspaper print his name alongside the {unit}?",
                f"because {ref_label(ref, claim)} places him in the {unit}", "unit->newspapers",
                Plan(handler="chronam", query=f"{sname} {state} {arm.split()[-1]}", years=(1861, 1866)),
                3, parent=ref, parent_q=qid, about=about)

        for m in SHIP.finditer(text):
            kind, ship, port = m.group(1), m.group(2), m.group(3)
            if kind.lower() != "ship" or port:
                label = f"{ship} of {port}" if port else ship
                add(_key("ship", ship, port or ""), f"Which voyages did the {kind} {label} make, and is he in a crew list or logbook?",
                    f"because {ref_label(ref, claim)} says \"{short}\"", "ship->voyages",
                    Plan(handler="ia_fulltext", query=f'"{ship} of {port}"' if port else f'"{kind} {ship}"'),
                    6, parent=ref, parent_q=qid, about=about, bonus_words=("ship", "whal", "sea", "voyage"))
                add(_key("ship-news", ship, port or ""), f"Did newspapers report the {label}'s sailings?",
                    f"because {ref_label(ref, claim)} names the {label}", "ship->newspapers",
                    Plan(handler="chronam", query=f"{ship} {port or ''} whaling".strip(), years=_years(p)),
                    3, parent=ref, parent_q=qid, about=about)

        def _names_subject(m, who):
            # Only use "son of A and B" when the subject's own given name sits just before it,
            # so a sibling or neighbour on the same page does not become his parents.
            given = (who or "").split()[0] if who else ""
            before = text[max(0, m.start() - 70):m.start()]
            last_name_before = re.findall(r"\b([A-Z][a-z]+)\s+(?:[A-Z]\.\s*)*[A-Z][a-z]+,?\s*$", before)
            return bool(given) and given in before and (not last_name_before or last_name_before[-1] == given)

        if about is None:
            for m in PARENTS.finditer(text):
                if not _names_subject(m, p.full_name):
                    continue
                father, mother, maiden = m.group(1), m.group(2), m.group(3)
                fam = f"{father} {sname}"
                add(_key("parents", father, mother), f"Who were his parents, {father} and {mother}{f' ({maiden})' if maiden else ''} {sname}?",
                    f"because {ref_label(ref, claim)} says \"{short}\"", "snippet->parents",
                    Plan(handler="ia_fulltext", query=f'"{fam}"'), 9, parent=ref, parent_q=qid, about=fam,
                    bonus_words=("parent", "father", "mother"))
        else:
            for m in PARENTS.finditer(text):
                if not _names_subject(m, about):
                    continue
                father, mother = m.group(1), m.group(2)
                fam = f"{father} {sname}"
                add(_key("parents", about, father, mother), f"Who were {about}'s parents, {father} and {mother}?",
                    f"because {ref_label(ref, claim)} says \"{short}\"", "snippet->grandparents",
                    Plan(handler="ia_fulltext", query=f'"{fam}"'), 8, parent=ref, parent_q=qid, about=fam)

        for m in COLLECTION.finditer(text):
            lib = m.group(1).strip()
            add(_key("collection", lib), f"What is in the {lib} collection about the {sname} family?",
                f"because {ref_label(ref, claim)} says \"{short}\"", "snippet->collection",
                Plan(handler="stub", why_stub="Local archive catalogues are not a keyless API. The system drafts a letter for a human to send; nothing is sent here."),
                3, parent=ref, parent_q=qid, about=about)

        if claim and claim.field == "marriage":
            mm = MARRIAGE_PLACE.search(text)
            if mm:
                yr, town, st = mm.groups()
                add(_key("marriage-church", town), f"Is the {yr} marriage in the {town} church or town register?",
                    f"because {claim.id} says \"{short}\"", "marriage->church",
                    Plan(handler="ia_title", query=f'title:("{town}") AND title:(church OR vital OR marriages OR records)'),
                    3, parent=ref, about=about, bonus_words=("married", "church"))

        for m in SCHOOL.finditer(text):
            inst = m.group(1)
            add(_key("school", inst), f"Do {inst} registers, catalogues or yearbooks list him?",
                f"because {ref_label(ref, claim)} says \"{short}\"", "school->registers",
                Plan(handler="ia_title", query=f'"{inst}" AND title:(register OR catalogue OR catalog OR yearbook OR alumni)'),
                4, parent=ref, parent_q=qid, about=about, bonus_words=("school", "college", "educat"))

        for m in ORG.finditer(text):
            org = m.group(1).strip()
            add(_key("org", org), f"What do the {org}'s own bulletins and records say?",
                f"because {ref_label(ref, claim)} says \"{short}\"", "congregation->records",
                Plan(handler="ia_title", query=f'"{org}"'), 4, parent=ref, parent_q=qid, about=about,
                bonus_words=("church", "synagogue", "temple"))

        if claim and claim.field == "residence":
            m = RESIDENCE.search(text)
            if m:
                town = m.group(1)
                add(_key("church", town), f"Which church served {town}, and do its records survive?",
                    f"because {claim.id} says \"{short}\"", "place->church",
                    Plan(handler="ia_title", query=f'title:("{town}") AND title:(church OR congregational OR parish)'),
                    3, parent=ref, about=about, bonus_words=("church",))

        if claim and claim.field == "death" and p.death_year:
            add(_key("obit", sname, str(p.death_year)), f"Was there an obituary for him in {p.death_year}?",
                f"because {claim.id} says \"{short}\"", "death->obituary",
                Plan(handler="chronam", query=f"{gname} {sname} {home_town}".strip(), years=(p.death_year, p.death_year + 1)),
                4, parent=ref, about=about, bonus_words=("buried", "died", "obituar"))

    # Book hits: search inside each book for him.
    for f in inp.findings:
        for cit in f.citations:
            if not cit.item_id:
                continue
            who = f.about or p.full_name
            t = (cit.title or "").lower()
            rel = 0
            rel += 3 if surname(Person(full_name=who)).lower() in t else 0
            rel += 2 if any(w in t for w in ("regiment", "volunteer", "artillery", "infantry", "rebellion")) else 0
            rel += 2 if home_town and home_town.lower() in t else 0
            rel += 1 if cit.name_match == "strong" else 0
            if v2:
                if f.about is None and not _in_life(p, (cit.snippet or "") + " " + (cit.title or ""), cit.year):
                    continue
                if node is not None and node.plan.handler == "ia_inside":
                    continue  # the page came from inside this very book: searching it again repeats the same call
            add(_key("inside", (cit.item_id if v2 else (cit.title or cit.item_id)[:60]), who), f"Does \"{(cit.title or cit.item_id)[:80]}\" name {who.split()[0]}, and on which page?",
                f"because {f.step_id} turned up this book", "book->inside",
                Plan(handler="ia_inside", item_id=cit.item_id, query=(surname2 if v2 else surname)(Person(full_name=who))),
                4 + rel, parent=cit.url, parent_q=f.step_id if f.step_id.startswith("q") else None, about=f.about)

    # Wikidata candidates that matched the years: ask for parents there.
    for f in (inp.findings if node is None else []):
        if f.source_slug == "wikidata" and f.status == "found":
            for cit in f.citations:
                add(_key("wd-kin", cit.url or ""), f"Who does Wikidata list as his parents and spouse?",
                    f"because {f.step_id} matched {cit.title}", "wikidata->kin",
                    Plan(handler="wikidata_kin", query=(cit.url or "").rsplit("/", 1)[-1]), 3, parent=cit.url)

    # Generic nudges on a node: are you sure? where else might this be?
    if node is not None:
        who = node.about or p.full_name
        t, _ = town_state(p.birth_place or p.death_place)
        weak = any(c.name_match == "surname_only" for c in node.citations) or node.plan.handler == "chronam"
        if node.status == "answered" and weak and req.verify_nodes:
            add(_key("verify", who, t), f"Are you sure the hits for \"{node.text[:60]}\" are the same {who.split()[0]}?",
                f"because {node.id} matched on the surname or in a newspaper, not on his full name and place",
                "node->are-you-sure", Plan(handler="ia_fulltext", query=f'"{who}" "{t}"' if t else f'"{who}"'), 4,
                parent=node.id, parent_q=node.id, about=node.about)
        alt = "chronam" if node.plan.handler != "chronam" else "ia_fulltext"
        alt_q = f"{who} {t}".strip() if alt == "chronam" else f'"{who}"'
        add(_key("elsewhere", alt, node.about or "", node.template), f"Where else might this be? Try {'newspapers' if alt == 'chronam' else 'books'} for {who}.",
            f"because {node.id} {'found nothing' if node.status == 'no_lead' else 'only searched ' + node.plan.handler}",
            "node->where-else", Plan(handler=alt, query=alt_q, years=_years(p) if alt == "chronam" else None),
            2 if node.status == "answered" else 3, parent=node.id, parent_q=node.id, about=node.about)

    # Checklist gaps, said plainly.
    gaps = [g for g in checklist(req, inp.findings) if g.state == "missing"] if node is None else []
    circuit = CIRCUITS[req.circuit_id]
    for g in gaps:
        topic = next(t for t in circuit.topics if t.id == g.topic)
        why = next((STEPS[s].why_stub for s in topic.steps if STEPS[s].mode == "stub"), "No keyless source covers this.")
        add(_key("gap", g.topic), f"Still nothing on {g.label.lower()}: where else could it be?",
            f"because the {circuit.title} checklist has no record for {g.label.lower()}", "checklist->gap",
            Plan(handler="stub", why_stub=why), 1 + (2 if g.asked else 0), parent=f"gap:{g.topic}")

    ungrounded = [q for q in ideas if not grounded(q)]
    ideas = [q for q in ideas if grounded(q)]
    fresh, dupes, seen = [], 0, set(asked) if req.dedupe else set()
    sig = lambda q: (q.plan.handler, q.plan.query, q.plan.item_id, tuple(q.plan.years or ()))  # noqa: E731
    seen_plans = {sig(q) for q in inp.questions if q.plan} if v2 else set()
    for q in sorted(ideas, key=lambda q: (-q.score, q.id)):
        if req.dedupe and q.key in seen:
            dupes += 1
            continue
        if v2 and q.plan.handler != "stub" and sig(q) in seen_plans:
            dupes += 1  # v2: same call under a different key
            continue
        seen.add(q.key)
        seen_plans.add(sig(q))
        fresh.append(q)
    live = [q for q in fresh if q.plan.handler != "stub"]
    stubs = [q for q in fresh if q.plan.handler == "stub"]
    picked = live[: inp.top_n] + stubs[:2]
    held = live[inp.top_n:] + stubs[2:]
    for i, q in enumerate(picked, 1):
        q.id = f"{node.id}.{i}" if node is not None else f"q{i}"
        q.parent_id = node.id if node is not None else "root"
        q.parent_question = node.id if node is not None else None
        q.depth = inp.depth
        q.round = inp.round
    return BrainstormOutput(round=inp.round, generated=len(ideas) + len(ungrounded), duplicates_skipped=dupes,
                            ungrounded_rejected=len(ungrounded), picked=picked, held_back=held[:12])


def ref_label(ref: str, claim: Claim | None) -> str:
    if claim:
        return claim.id
    if ref and ref.startswith("http"):
        return "a book page" if "archive.org" in ref else "a record"
    return ref or "a finding"
