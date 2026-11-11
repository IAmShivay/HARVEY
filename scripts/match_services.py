"""Note which of your services fits each lead that already has drafts.

The Writer does this for new leads (harvey/service_match.py). Run this once
for leads written before product.services was set, or after changing it.
Internal only: nothing here touches an email.

    python scripts/match_services.py            # leads without a pick yet
    python scripts/match_services.py --all      # redo every lead
    python scripts/match_services.py --verified-only   # only sendable leads
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUED_STATUSES = ("queued", "contacted", "replied")
SENDABLE_EMAIL_STATUS = "verified"


async def run(redo: bool, verified_only: bool) -> int:
    sys.path.insert(0, str(ROOT))
    from harvey.brain import Brain
    from harvey.config import load_config, load_env
    from harvey.service_match import lead_emails, load_pick, pick_service, save_pick, services_of
    from harvey.state import StateManager

    load_env()
    config = load_config()
    if not services_of(config):
        print("product.services is empty in your config; nothing to match.")
        return 1
    state = StateManager()
    await state.init_db()
    brain = Brain(state, config.brain)

    done = 0
    for status in QUEUED_STATUSES:
        for p in await state.get_prospects_by_status(status):
            if verified_only and p.email_status != SENDABLE_EMAIL_STATUS:
                continue
            if not redo and await load_pick(state, p.id):
                continue
            emails = await lead_emails(state, p.id)
            pick = await pick_service(brain, config, p.company, p.personalization_notes or "", emails)
            if pick:
                await save_pick(state, p.id, pick)
                done += 1
                print(f"{p.company:<32} -> {pick['service']}")
            else:
                print(f"{p.company:<32} -> (no match{': ' + brain.paused_reason if brain.paused_reason else ''})")
    print(f"Matched {done} lead(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="Redo leads that already have a pick")
    parser.add_argument("--verified-only", action="store_true",
                        help="Only leads with a verified (sendable) address")
    args = parser.parse_args()
    return asyncio.run(run(args.all, args.verified_only))


if __name__ == "__main__":
    sys.exit(main())
