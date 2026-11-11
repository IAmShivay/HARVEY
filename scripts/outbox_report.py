"""Read-only JSON report of Outbox drafts, for the Harvey MCP server.

    python scripts/outbox_report.py                    # pending drafts
    python scripts/outbox_report.py --email-status verified
    python scripts/outbox_report.py --id 7cc72956188f  # one full draft
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "harvey.db"
PENDING = "pending_review"
DEFAULT_LIMIT = 50
PREVIEW_CHARS = 160

SERVICE_PICK_KEY = "service_pick:"

LIST_SQL = """
select o.id, o.to_email, o.step, o.subject, o.body, o.send_at,
       coalesce(p.email_status, '') as email_status, coalesce(p.company, '') as company,
       s.value as service_pick
from outbox o left join prospects p on p.id = o.prospect_id
left join settings s on s.key = ? || o.prospect_id
where o.status = ?
"""


def with_pick(item: dict, full: bool) -> dict:
    """Attach the internal service note (never part of the email)."""
    raw = item.pop("service_pick", None)
    try:
        pick = json.loads(raw) if raw else None
    except ValueError:
        pick = None
    if pick:
        item["you_sell"] = pick if full else pick.get("service", "")
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--id", help="Return one draft in full")
    parser.add_argument("--status", default=PENDING)
    parser.add_argument("--email-status", help="verified, risky, guess or invalid")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if args.id:
        row = conn.execute(LIST_SQL.replace("where o.status = ?", "where o.id = ?"),
                           (SERVICE_PICK_KEY, args.id)).fetchone()
        print(json.dumps(with_pick(dict(row), full=True) if row else {"error": f"no draft {args.id}"}, indent=2))
        return 0

    sql, params = LIST_SQL, [SERVICE_PICK_KEY, args.status]
    if args.email_status:
        sql += " and coalesce(p.email_status, '') = ?"
        params.append(args.email_status)
    sql += " order by o.send_at limit ?"
    params.append(args.limit)

    rows = []
    for r in conn.execute(sql, params):
        item = with_pick(dict(r), full=False)
        item["preview"] = " ".join(item.pop("body").split())[:PREVIEW_CHARS]
        rows.append(item)
    total = conn.execute("select count(*) from outbox where status = ?", (args.status,)).fetchone()[0]
    print(json.dumps({"total_with_status": total, "returned": len(rows), "drafts": rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
