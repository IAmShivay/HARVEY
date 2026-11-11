"""Harvey + Oracle servers as MCP tools for Claude Desktop.

A fixed set of tools, no arbitrary shell. Harvey runs either on this PC
(HARVEY_HOST empty) or on a server reached over SSH (HARVEY_HOST=user@ip).
"""

import json
import os
import re
import shlex
import subprocess

from mcp.server.fastmcp import FastMCP

HARVEY_HOST = os.environ.get("HARVEY_HOST", "").strip()
HARVEY_DIR = os.environ.get("HARVEY_DIR", r"D:\GRAPHITAGE\harvey")
HARVEY_RUN_AS = os.environ.get("HARVEY_RUN_AS", "").strip()
SSH_KEY = os.path.expanduser(os.environ.get("SSH_KEY", "~/.ssh/oci_a1"))
A1_HOST = os.environ.get("A1_RETRY_HOST", "").strip()
A1_LOG = os.environ.get("A1_RETRY_LOG", "~/oci-a1-retry/a1_retry.log")
SERVER_HOSTS = [h.strip() for h in os.environ.get("SERVER_HOSTS", "").split(",") if h.strip()]

COMMAND_TIMEOUT_SECONDS = 180
SSH_CONNECT_TIMEOUT_SECONDS = 20
A1_LOG_LINES_MAX = 50
DRAFT_LIST_MAX = 200
DRAFT_ID = re.compile(r"^[0-9a-f]{6,32}$")
EMAIL_STATUSES = {"verified", "risky", "guess", "invalid"}

mcp = FastMCP("harvey")


def _ssh(host: str, command: str) -> list[str]:
    return ["ssh", "-n", "-i", SSH_KEY, "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}", host, command]


def _run(argv: list[str], cwd: str | None = None) -> str:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"timed out after {COMMAND_TIMEOUT_SECONDS}s"
    out = (done.stdout or "").strip()
    err = (done.stderr or "").strip()
    if done.returncode != 0:
        return f"exit {done.returncode}\n{out}\n{err}".strip()
    return out or err


def _harvey(args: list[str], script: str | None = None) -> str:
    """Run `harvey <args>` or `python scripts/<script> <args>` where Harvey lives."""
    if HARVEY_HOST:
        exe = ".venv/bin/python" if script else ".venv/bin/harvey"
        parts = [exe] + ([f"scripts/{script}"] if script else []) + args
        command = f"cd {shlex.quote(HARVEY_DIR)} && " + " ".join(shlex.quote(p) for p in parts)
        if HARVEY_RUN_AS:
            command = f"sudo -n -u {shlex.quote(HARVEY_RUN_AS)} -H bash -c {shlex.quote(command)}"
        return _run(_ssh(HARVEY_HOST, command))
    bin_dir = os.path.join(HARVEY_DIR, ".venv", "Scripts")
    if script:
        argv = [os.path.join(bin_dir, "python.exe"), os.path.join("scripts", script)] + args
    else:
        argv = [os.path.join(bin_dir, "harvey.exe")] + args
    return _run(argv, cwd=HARVEY_DIR)


def _valid_ids(ids: list[str]) -> list[str]:
    bad = [i for i in ids if not DRAFT_ID.match(i or "")]
    if bad:
        raise ValueError(f"not draft ids: {bad}")
    return ids


@mcp.tool()
def harvey_status() -> str:
    """Harvey's pipeline: prospects, campaigns, conversations and Claude usage today."""
    return _harvey(["status"])


@mcp.tool()
def list_drafts(email_status: str = "", limit: int = 50) -> str:
    """Drafts waiting in Harvey's Outbox for approval, with recipient, email check
    (verified/risky/guess/invalid), step, subject and a preview. Only 'verified'
    addresses can actually be sent."""
    args = ["--limit", str(max(1, min(limit, DRAFT_LIST_MAX)))]
    if email_status:
        if email_status not in EMAIL_STATUSES:
            return f"email_status must be one of {sorted(EMAIL_STATUSES)}"
        args += ["--email-status", email_status]
    return _harvey(args, script="outbox_report.py")


@mcp.tool()
def read_draft(draft_id: str) -> str:
    """The full text of one Outbox draft."""
    return _harvey(["--id", *_valid_ids([draft_id])], script="outbox_report.py")


@mcp.tool()
def approve_drafts(draft_ids: list[str]) -> str:
    """Approve Outbox drafts by id. Approved emails send on Harvey's schedule:
    recipient office hours, at most 10 cold emails a day, spaced out."""
    return _harvey(["approve", *_valid_ids(draft_ids)], script="outbox_actions.py")


@mcp.tool()
def reject_drafts(draft_ids: list[str]) -> str:
    """Reject Outbox drafts by id so they are never sent."""
    return _harvey(["reject", *_valid_ids(draft_ids)], script="outbox_actions.py")


@mcp.tool()
def reject_risky_drafts() -> str:
    """Reject every pending cold draft whose address is not verified
    (risky, guessed or invalid). Harvey would never send those anyway."""
    return _harvey(["reject-unsendable"], script="outbox_actions.py")


@mcp.tool()
def retry_failed_writes() -> str:
    """Retry contacts Harvey gave up writing for (3 unusable drafts in a row,
    status write_failed). Usage-limit pauses already retry on their own."""
    return _harvey(["retry-writes"])


@mcp.tool()
def sending_status() -> str:
    """Whether Harvey's sending kill switch is active or paused."""
    return _harvey(["sending", "status"])


@mcp.tool()
def pause_sending() -> str:
    """Pause all of Harvey's sending immediately. Drafts and approvals are kept."""
    return _harvey(["sending", "pause"])


@mcp.tool()
def resume_sending() -> str:
    """Resume Harvey's sending after a pause."""
    return _harvey(["sending", "resume"])


@mcp.tool()
def a1_status(lines: int = 10) -> str:
    """Latest results of the Oracle A1 free-server retry running on micro-1."""
    if not A1_HOST:
        return "A1_RETRY_HOST is not configured"
    n = max(1, min(lines, A1_LOG_LINES_MAX))
    return _run(_ssh(A1_HOST, f"tail -n {n} {A1_LOG}; echo; crontab -l | grep a1_retry"))


@mcp.tool()
def servers_health() -> str:
    """RAM, disk, load and uptime of each Oracle server."""
    if not SERVER_HOSTS:
        return "SERVER_HOSTS is not configured"
    probe = "hostname; uptime -p; free -m | sed -n 2p; df -h / | sed -n 2p"
    return "\n\n".join(f"== {h}\n{_run(_ssh(h, probe))}" for h in SERVER_HOSTS)


if __name__ == "__main__":
    mcp.run()
