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
Pure and deterministic; it runs inside an activity so the logic can later be
swapped for a model without touching workflow code.
"""

from __future__ import annotations

import re

from studio.circuits import CIRCUITS, STEPS
from studio.models import (
    BrainstormInput, BrainstormOutput, Citation, Claim, Finding, Gap, Person, Plan, Question, ResearchRequest,
)
from studio.names import ORD, WORD2NUM, given, match, surname, town_state

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


def _key(*parts: str) -> str:
    return ":".join(re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-") for p in parts if p)


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


def brainstorm(inp: BrainstormInput) -> BrainstormOutput:
    req, p = inp.request, inp.request.person
    sname, gname = surname(p), given(p)
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
            "Checklist round done; books often hold what indexes miss", "name->books",
            Plan(handler="ia_fulltext", query=f'"{nm}"'), 9 if nm == names[0] else 5, bonus_words=("book", "mention"))

    for text, ref, f, cit, claim in _texts(inp.findings):
        about = f.about  # None = the subject
        who = about or p.full_name
        target = Person(full_name=who)
        strong = cit is None or cit.name_match in (None, "strong") or (cit.snippet and match(target, cit.snippet) == "strong")
        if not strong:
            continue
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
                Plan(handler="stub", why_stub="Local archive catalogues are not a keyless API. Lineage drafts a letter for a human to send; nothing is sent here."),
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
            add(_key("inside", (cit.title or cit.item_id)[:60], who), f"Does \"{(cit.title or cit.item_id)[:80]}\" name {who.split()[0]}, and on which page?",
                f"because {f.step_id} turned up this book", "book->inside",
                Plan(handler="ia_inside", item_id=cit.item_id, query=surname(Person(full_name=who))),
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
        if node.status == "answered" and weak:
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
            Plan(handler="stub", why_stub=why), 1 + (2 if g.asked else 0))

    fresh, dupes, seen = [], 0, set(asked)
    for q in sorted(ideas, key=lambda q: (-q.score, q.id)):
        if q.key in seen:
            dupes += 1
            continue
        seen.add(q.key)
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
    return BrainstormOutput(round=inp.round, generated=len(ideas), duplicates_skipped=dupes, picked=picked, held_back=held[:12])


def ref_label(ref: str, claim: Claim | None) -> str:
    if claim:
        return claim.id
    if ref and ref.startswith("http"):
        return "a book page" if "archive.org" in ref else "a record"
    return ref or "a finding"
