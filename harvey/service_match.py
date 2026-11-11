"""Which of your services fits each lead, for you only.

After the Writer drafts a lead's emails, one brain call picks the service
from product.services that best fits the problem those emails raise, says
why, and lists what to show in the store review. The result is stored next
to the lead (settings key service_pick:<prospect id>) and shown wherever you
review drafts. It is never put into an email and never fed back to the
Writer. With product.services empty, nothing runs.
"""

import json
import logging

from harvey.untrusted import UNTRUSTED_RULE, fence

logger = logging.getLogger("harvey.service_match")

SERVICE_PICK_KEY = "service_pick:"
MAX_LOOM_POINTS = 3
MAX_TEXT_CHARS = 300


def services_of(config) -> list:
    return list(getattr(getattr(config, "product", None), "services", None) or [])


def _menu(services) -> str:
    return "\n".join(
        f"- {s.name}: fixes {s.solves}"
        + (f" (first project: {s.first_project})" if s.first_project else "")
        for s in services)


def build_prompt(services, company: str, notes: str, emails: list[dict]) -> str:
    drafts = "\n\n".join(
        f"{'Email 1 (written for this lead)' if i == 0 else f'Follow-up {i}'} - "
        f"{e.get('subject', '')}\n{e.get('body', '')}"
        for i, e in enumerate(emails))
    return f"""You are helping an agency owner prepare for a sales conversation. This is an
internal note for them only. It is never sent to anyone.

Their services:
{_menu(services)}

Lead: {company}
{fence(notes or "(none)", "notes about the lead")}
{fence(drafts, "cold emails already written to this lead, in send order")}

{UNTRUSTED_RULE}
Pick the ONE service from the list that best fixes this lead's own problem: the one
email 1 and the notes describe. The follow-ups reuse the same case study for every
lead, so don't pick a service just because a follow-up mentions it.
Use the service name exactly as written in the list.

Return ONLY a JSON object:
{{"service": "<exact service name>", "why": "<one sentence: the lead's problem and why this service fits>", "loom_points": ["<what to show in a 2-minute review of their store>", "...", "..."]}}"""


def parse_pick(result, services) -> dict | None:
    """The validated pick, or None when the reply doesn't name a listed service."""
    if not isinstance(result, dict):
        return None
    by_name = {s.name.strip().lower(): s for s in services}
    chosen = by_name.get(str(result.get("service", "")).strip().lower())
    if chosen is None:
        return None
    points = result.get("loom_points") or []
    if not isinstance(points, list):
        points = []
    return {
        "service": chosen.name,
        "first_project": chosen.first_project,
        "why": str(result.get("why", "")).strip()[:MAX_TEXT_CHARS],
        "loom_points": [str(p).strip()[:MAX_TEXT_CHARS] for p in points if str(p).strip()][:MAX_LOOM_POINTS],
    }


async def lead_emails(state, prospect_id: str, sequence=None) -> list[dict]:
    """The lead's cold emails in step order: their own Outbox drafts, with
    campaign template steps filling any step not staged yet."""
    async with state._connect() as db:
        async with db.execute(
                "SELECT step, subject, body FROM outbox WHERE prospect_id = ? "
                "AND kind = 'sequence' ORDER BY step, created_at", (prospect_id,)) as cur:
            rows = await cur.fetchall()
    by_step = {}
    for step, subject, body in rows:
        by_step.setdefault(int(step), {"subject": subject or "", "body": body or ""})
    for s in sequence or []:
        by_step.setdefault(int(s.step), {"subject": s.subject, "body": s.body})
    return [by_step[k] for k in sorted(by_step)]


async def pick_service(brain, config, company: str, notes: str, emails: list[dict]) -> dict | None:
    services = services_of(config)
    if not services or not emails:
        return None
    result = await brain.think_json(build_prompt(services, company, notes, emails),
                                    agent="writer", task="service_match")
    return parse_pick(result, services)


async def save_pick(state, prospect_id: str, pick: dict) -> None:
    await state.set_setting(SERVICE_PICK_KEY + prospect_id, json.dumps(pick))


async def load_pick(state, prospect_id: str) -> dict | None:
    raw = await state.get_setting(SERVICE_PICK_KEY + prospect_id)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None
