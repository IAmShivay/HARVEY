"""Approve or reject Outbox drafts in one call, for the Harvey MCP server.

Uses Harvey's own StateManager, the same methods as `harvey outbox`.

    python scripts/outbox_actions.py approve ID [ID ...]
    python scripts/outbox_actions.py reject ID [ID ...]
    python scripts/outbox_actions.py reject-unsendable   # drafts to non-verified addresses
"""

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING = "pending_review"
SENDABLE_EMAIL_STATUS = "verified"


def unsendable_ids(db_path: str) -> list[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute(
        "select o.id from outbox o left join prospects p on p.id = o.prospect_id "
        "where o.status = ? and o.kind = 'sequence' and coalesce(p.email_status, '') != ?",
        (PENDING, SENDABLE_EMAIL_STATUS)).fetchall()
    return [r[0] for r in rows]


async def run(action: str, ids: list[str]) -> dict:
    sys.path.insert(0, str(ROOT))
    from harvey.state import StateManager

    state = StateManager()
    await state.init_db()
    if action == "reject-unsendable":
        ids, action = unsendable_ids(state.db_path), "reject"

    done, missed = [], []
    for item_id in ids:
        if action == "approve":
            ok = await state.approve_outbox(item_id)
        else:
            ok = await state.reject_outbox_item(item_id)
        (done if ok else missed).append(item_id)
    return {"action": action, "done": done, "not_pending": missed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["approve", "reject", "reject-unsendable"])
    parser.add_argument("ids", nargs="*")
    args = parser.parse_args()
    if args.action != "reject-unsendable" and not args.ids:
        parser.error("give at least one draft id")
    print(json.dumps(asyncio.run(run(args.action, args.ids)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
