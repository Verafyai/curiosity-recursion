"""Outreach: drafts only, ask-first, never sent.

A STUB question that needs a human (a pension file, a town clerk, a museum collection) becomes
an `OutreachDraft`. It waits for the reviewer's `outreach_decision` signal. Approving writes a
text file to CR_OUTBOX (default data/outbox-not-sent/) for the person to send themselves.
No mail transport or messaging client exists anywhere in this package; tests/test_no_send.py checks.
Letters never invent an address: they point to where the real one is listed.
"""
from __future__ import annotations

import os
from pathlib import Path

from temporalio import activity

from cr.models import OutreachDraft, Question
from cr.names import town_state

ROOT = Path(__file__).resolve().parent.parent


def outbox() -> Path:
    return Path(os.environ.get("CR_OUTBOX", ROOT / "data" / "outbox-not-sent"))


def draft_outreach(q: Question, req) -> OutreachDraft | None:
    p = req.person
    town, state = town_state(p.birth_place or p.death_place)
    years = f"{p.birth_year or '?'} to {p.death_year or '?'}"
    t = q.template + " " + q.key
    if "pension" in t:
        to, ch, hint = "National Archives and Records Administration (NARA), Washington, DC", "web_form", "Order Civil War pension files through archives.gov (NATF Form 85). Check current fees there; nothing is filled in here."
        ask = "a copy of any Civil War pension application file, or confirmation that none exists"
    elif "collection" in t:
        lib = q.text.split("in the ")[1].split(" collection")[0] if "in the " in q.text else "the local history library"
        to, ch, hint = lib, "letter", "Use the contact page on the institution's own website."
        ask = f"a list of items in your collection that mention {p.full_name}"
    elif any(k in t for k in ("unit", "census", "birth", "death", "marriage", "settling", "origin", "children", "parents", "passage", "naturalization", "work")):
        if state.lower() == "connecticut":
            to, ch, hint = "Connecticut State Library, State Archives (Hartford)", "letter", "The State Library takes research requests by letter; use the address on its own homepage."
        else:
            to, ch, hint = f"Town or county clerk, {town or 'the town where they lived'}", "letter", "Use the clerk's official website for the mailing address."
        ask = f"any {q.text.split(':')[0].replace('Still nothing on ', '').strip()} records you hold"
    else:
        return None
    body = (
        f"Hello,\n\nI am researching my relative {p.full_name} ({years}"
        f"{', ' + (p.birth_place or p.death_place) if (p.birth_place or p.death_place) else ''}). "
        f"Could you tell me whether you hold {ask}? "
        f"So far the record shows: {q.because}.\n\n"
        "I am happy to pay any copying fee you charge; please tell me the amount before you send anything.\n\n"
        "Thank you,\n[Your name]\n[Your return address]"
    )
    return OutreachDraft(id=f"req-{q.id}", node_id=q.id, to=to, channel=ch, contact_hint=hint,
                         subject=f"Research request: {p.full_name} ({years})", body=body)


@activity.defn
async def export_outreach(draft: OutreachDraft) -> OutreachDraft:
    """Approved requests are written to a local folder for the user to send themselves. Nothing is sent."""
    box = outbox()
    box.mkdir(parents=True, exist_ok=True)
    wid = activity.info().workflow_id
    path = box / f"{wid}--{draft.id}.txt"
    path.write_text(f"NOT SENT. Approved draft exported by curiosity-recursion (local).\nTo: {draft.to}\nHow to reach them: {draft.contact_hint}\n"
                    f"Subject: {draft.subject}\n\n{draft.body}\n")
    d = draft.model_copy()
    d.exported_to = str(path)
    return d
