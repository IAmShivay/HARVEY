"""Daily deliverability alert: push to ntfy when mail starts heading for spam.

Reads the same numbers as `harvey warmup`: the TrulyInbox warmup inbox rate
for the sending mailbox and Harvey's own bounce count. Sends a high-priority
push when either crosses its threshold, otherwise one quiet daily line.

    python scripts/deliverability_alert.py            # check and push
    python scripts/deliverability_alert.py --dry-run  # print only

Needs DELIVERABILITY_NTFY_TOPIC in .env.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent

NTFY_URL = "https://ntfy.sh"
NTFY_TOPIC_ENV = "DELIVERABILITY_NTFY_TOPIC"
NTFY_TIMEOUT_SECONDS = 20
MIN_INBOX_RATE = 0.90
MAX_BOUNCE_RATE = 0.02
MIN_SENDS_FOR_BOUNCE_RATE = 20
PRIORITY_ALERT = "high"
PRIORITY_OK = "low"


async def gather() -> dict:
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from harvey.agents.handler import BOUNCE_COUNT_KEY
    from harvey.config import load_config, load_env
    from harvey.integrations.trulyinbox import current_health, sending_address
    from harvey.state import StateManager

    load_env()
    config = load_config()
    state = StateManager()
    await state.init_db()
    address = sending_address(config)
    health, error = await current_health(address)
    return {
        "address": address,
        "health": health,
        "health_error": error,
        "sent": await state.count_outbox_sent(),
        "bounces": int(await state.get_setting(BOUNCE_COUNT_KEY) or 0),
    }


def evaluate(data: dict) -> tuple[list[str], list[str]]:
    """(problems, facts) as short human lines."""
    problems, facts = [], []
    health = data["health"]
    if data["health_error"]:
        problems.append(f"TrulyInbox check failed: {data['health_error']}")
    elif health is None:
        facts.append("TrulyInbox not connected")
    elif not health.found:
        problems.append(f"TrulyInbox doesn't know {data['address']}")
    elif health.spam_rate is None:
        facts.append("warmup: no emails in the report window yet")
    else:
        inbox = 1 - health.spam_rate
        line = f"warmup inbox {inbox:.0%} ({health.spam} spam / {health.sent})"
        (problems if inbox < MIN_INBOX_RATE else facts).append(
            line + (f" - below {MIN_INBOX_RATE:.0%}, slow down sending" if inbox < MIN_INBOX_RATE else ""))
        if not health.login_ok:
            problems.append("TrulyInbox can't log in to the mailbox (warmup stopped)")

    sent, bounces = data["sent"], data["bounces"]
    if sent >= MIN_SENDS_FOR_BOUNCE_RATE:
        rate = bounces / sent
        line = f"bounces {rate:.1%} ({bounces}/{sent})"
        (problems if rate > MAX_BOUNCE_RATE else facts).append(
            line + (f" - above {MAX_BOUNCE_RATE:.0%}" if rate > MAX_BOUNCE_RATE else ""))
    else:
        facts.append(f"bounces {bounces}/{sent} sent (too few to judge)")
    return problems, facts


def push(topic: str, title: str, body: str, priority: str) -> None:
    httpx.post(f"{NTFY_URL}/{topic}", content=body.encode(),
               headers={"Title": title, "Priority": priority},
               timeout=NTFY_TIMEOUT_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = asyncio.run(gather())
    problems, facts = evaluate(data)
    if problems:
        title = "Deliverability WARNING"
        body = "\n".join(problems + facts)
        priority = PRIORITY_ALERT
    else:
        title = "Deliverability OK"
        body = ", ".join(facts)
        priority = PRIORITY_OK

    print(f"{title}\n{body}")
    topic = os.getenv(NTFY_TOPIC_ENV, "").strip()
    if args.dry_run:
        return 0
    if not topic:
        print(f"{NTFY_TOPIC_ENV} not set; nothing pushed")
        return 1
    push(topic, title, body, priority)
    return 0


if __name__ == "__main__":
    sys.exit(main())
