"""Drive an MCP server over stdio: send requests, wait for each reply, then close.

Piping a file into the server closes its stdin at EOF, and a server that is
still running a slow tool exits before it answers -- which looks like a lost
response and is actually a lost client. So requests are written one at a
time and each reply is awaited before stdin is closed.
"""
import json
import subprocess
import sys

cmd = sys.argv[1:]
reqs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "ci", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "detect_pii",
                "arguments": {"text": "Adaeze Okonkwo, NIN 12345678901", "jurisdiction": "NG"}}},
]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                     encoding="utf-8")
replies = []
for r in reqs:
    p.stdin.write(json.dumps(r) + "\n")
    p.stdin.flush()
    if "id" in r:
        line = p.stdout.readline()
        assert line, f"server closed before answering id={r['id']}"
        replies.append(json.loads(line))
p.stdin.close()
p.wait(timeout=30)
assert len(replies) == 3, replies
assert replies[0]["result"]["serverInfo"]["name"] == "arche"
names = {t["name"] for t in replies[1]["result"]["tools"]}
assert {"detect_pii", "compare_records"} <= names, names
body = replies[2]["result"]
assert not body.get("isError"), body
assert "NIN" in json.dumps(body), body
print("MCP handshake, tools/list and a detect_pii call all good;", len(names), "tools")
