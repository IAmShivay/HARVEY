# Harvey MCP

MCP server that lets Claude Desktop manage the Harvey sales agent and the Oracle Always Free servers. A fixed set of tools, no arbitrary shell.

| Tool | Does |
|---|---|
| `harvey_status` | Pipeline counts |
| `list_drafts` | Outbox drafts waiting for approval (filter by `verified`, `risky`, `guess`, `invalid`) |
| `read_draft` | One full draft |
| `approve_drafts` / `reject_drafts` | Approve or reject drafts by id |
| `reject_risky_drafts` | Reject every pending cold draft to a non-verified address |
| `retry_failed_writes` | Retry contacts Harvey gave up writing for (3 unusable drafts) |
| `sending_status` / `pause_sending` / `resume_sending` | Harvey's sending kill switch |
| `a1_status` | Latest A1 retry results from micro-1 |
| `servers_health` | RAM, disk and uptime of each server |

## Setup

```
cd mcp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

It uses `scripts/outbox_report.py` and `scripts/outbox_actions.py` from this repo.

Add to `%APPDATA%\Claude\claude_desktop_config.json` under `mcpServers`:

```json
"harvey": {
  "command": "D:\\GRAPHITAGE\\harvey\\mcp\\.venv\\Scripts\\python.exe",
  "args": ["D:\\GRAPHITAGE\\harvey\\mcp\\server.py"],
  "env": {
    "HARVEY_HOST": "",
    "HARVEY_DIR": "D:\\GRAPHITAGE\\harvey",
    "SSH_KEY": "C:\\Users\\<you>\\.ssh\\<key>",
    "A1_RETRY_HOST": "ubuntu@<micro-1-ip>",
    "SERVER_HOSTS": "ubuntu@<micro-1-ip>,ubuntu@<micro-2-ip>"
  }
}
```

`HARVEY_HOST` empty runs Harvey commands on this PC. Set it to `user@ip` (and `HARVEY_DIR` to the remote path) when Harvey runs on a server; commands then go over SSH with `SSH_KEY`. Set `HARVEY_RUN_AS` (e.g. `harvey`) to run them as that user via `sudo -u`.
