"""Re-check every company with the US brand filter (harvey/brand_filter.py).

Harvey already runs it after each profile pass when icp.us_brand_filter is
on. Use this to re-check the whole list at once, e.g. after tuning patterns.

    .venv\\Scripts\\python scripts\\us_brand_filter.py            # apply
    .venv\\Scripts\\python scripts\\us_brand_filter.py --dry-run  # report only
"""

import argparse
import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "data" / "us_brand_filter_report.txt"
BACKUP_PREFIX = "harvey.backup-filter-"


async def run(dry_run: bool) -> dict:
    sys.path.insert(0, str(ROOT))
    from harvey.brand_filter import filter_companies
    from harvey.config import load_config
    from harvey.state import StateManager

    state = StateManager()
    await state.init_db()
    if not dry_run:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        db = Path(state.db_path)
        shutil.copy2(db, db.with_name(f"{BACKUP_PREFIX}{stamp}.db"))
    return await filter_companies(state, load_config(), None, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    result = asyncio.run(run(args.dry_run))
    rows = sorted(result["results"], key=lambda r: (not r["keep"], r["domain"]))
    REPORT_PATH.write_text("\n".join(
        f"{'KEEP' if r['keep'] else 'DROP'}  {r['domain']:<40} {r['reason']}" for r in rows
    ) + "\n", encoding="utf-8")

    action = "would remove" if args.dry_run else "removed"
    print(f"Checked {result['checked']} companies: kept {result['kept']}, "
          f"{action} {result['removed']}.")
    print(f"Full report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
