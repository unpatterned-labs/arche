#!/usr/bin/env python
# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""Talk to arche in English, and watch a model decide which tools to call.

    uv run python packages/arche-mcp/chat.py
    uv run python packages/arche-mcp/chat.py "is this safe to send? NIN 12345678901"

This is the demo `demo.py` is not. `demo.py` calls the handler functions in a
fixed order, which shows that the engine works and says nothing about MCP.
This starts the real server as a subprocess, speaks JSON-RPC to it over stdio,
hands the tool schemas to a model, and lets the model choose. Nothing here
decides the order. If the model calls `guarded_scan` without checking coverage
first, you will see it do that, which is the point of watching.

Every tool call is printed before it runs and its result after, so the
transcript is the demo: you can see the model discover that a document is
Nigerian, look up whether a statute covers that, and only then redact.

Needs an OpenAI key. It reads `.env` in the repo root if present, and `.env` is
gitignored. There is deliberately no fallback to a hard-coded key and no
prompting for one.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

MODEL = os.environ.get("ARCHE_CHAT_MODEL", "gpt-4o-mini")
REPO = pathlib.Path(__file__).resolve().parents[2]

SYSTEM = """You are connected to arche, which resolves entity references and \
protects personal data.

Use the tools rather than answering from your own knowledge. You cannot see \
the documents the user describes unless you pass them to a tool.

Two flows exist and they share almost no tools:

RESOLUTION - are these two records the same thing?
  describe_pack -> compare_records

PROTECTION - what may leave this boundary, and on whose authority?
  infer_jurisdiction -> plan_protection -> guarded_scan

Before redacting anything, find out which law governs it. `infer_jurisdiction` \
returns `policy_available`; if that is false, no statute pack covers the \
document and you must say so rather than proceeding.

Read the `coverage` block on any result that has one. A tool that found \
nothing may have found nothing to find, or may have had no detector capable of \
looking. Those are different and the block distinguishes them. Say which \
happened.

A `review` decision is a real answer, not a failure. It means the records agree \
and nothing they agree on is distinctive enough to assert a match.

Be brief. Report what the tools returned, including what they refused."""


def load_env() -> None:
    """Read `.env` into the environment without printing any of it.

    Deliberately minimal rather than pulling in python-dotenv: this is a demo
    script and a dependency to parse `KEY=value` is not worth it. Existing
    environment variables win, so an operator can override the file.
    """
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def to_openai_tool(tool) -> dict:
    """One MCP tool as an OpenAI function definition.

    The description travels verbatim, and that matters more than it looks: for
    an MCP server the tool description IS the documentation, because it is the
    only thing the model reads. arche's descriptions carry the caveats — which
    text offsets index, that `partial` coverage is normal, that a field a pack
    does not name is ignored rather than rejected — so truncating them here
    would quietly remove the guidance the server exists to give.
    """
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            # `input_schema`, snake_case. The MCP SDK renamed it from
            # `inputSchema` in 2.0, the same generation that moved FastMCP to
            # MCPServer. Anything written against 1.x hits this.
            "parameters": tool.input_schema or {"type": "object", "properties": {}},
        },
    }


def show_result(text: str, limit: int = 700) -> None:
    """Print a tool result, pretty where it is JSON, truncated where it is long."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        print(f"      {text[:limit]}")
        return
    rendered = json.dumps(parsed, indent=2)
    lines = rendered.splitlines()
    for line in lines[:22]:
        print(f"      {line}")
    if len(lines) > 22:
        print(f"      ... {len(lines) - 22} more lines")


async def run(first_prompt: str | None) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from openai import OpenAI

    client = OpenAI()

    # The real server, as a subprocess, over stdio. Same command a client uses.
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(REPO), "arche-mcp"],
        env={**os.environ, "ARCHE_HASH_KEY": os.environ.get("ARCHE_HASH_KEY", "demo-key")},
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        tools = [to_openai_tool(t) for t in listed.tools]
        print(f"connected to arche-mcp: {len(tools)} tools, model {MODEL}")
        print("type a question, or 'quit'. try:")
        print('  "is this safe to send to a model? Dr Adaeze Okonkwo, NIN 12345678901, Kano"')
        print('  "are General Hospital and General Hospital the same place?"\n')

        messages: list[dict] = [{"role": "system", "content": SYSTEM}]
        pending = first_prompt

        while True:
            if pending is not None:
                user = pending
                pending = None
                print(f"you> {user}")
            else:
                try:
                    user = input("you> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
            if not user:
                continue
            if user.lower() in {"quit", "exit", "q"}:
                return

            messages.append({"role": "user", "content": user})

            # The agent loop. The model may call several tools before answering,
            # and may call one whose result changes its mind about the next.
            for _ in range(8):
                reply = client.chat.completions.create(
                    model=MODEL, messages=messages, tools=tools, tool_choice="auto",
                ).choices[0].message

                if not reply.tool_calls:
                    print(f"\narche> {reply.content}\n")
                    messages.append({"role": "assistant", "content": reply.content})
                    break

                messages.append(reply.model_dump(exclude_none=True))
                for call in reply.tool_calls:
                    args = json.loads(call.function.arguments or "{}")
                    shown = {k: (v[:60] + "..." if isinstance(v, str) and len(v) > 60 else v)
                             for k, v in args.items()}
                    print(f"\n  [tool] {call.function.name}({json.dumps(shown)[:110]})")

                    try:
                        result = await session.call_tool(call.function.name, args)
                        text = "".join(
                            c.text for c in result.content if getattr(c, "text", None))
                    except Exception as exc:  # noqa: BLE001 — report, never crash the loop
                        text = json.dumps({"error": str(exc)})
                        print(f"      ERROR {exc}")
                    else:
                        show_result(text)

                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "content": text})
            else:
                print("\narche> (stopped after 8 tool calls)\n")


def main() -> None:
    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit(
            "No OPENAI_API_KEY. Put it in .env at the repo root (gitignored) or "
            "export it. This script will not prompt for a key or fall back to one."
        )
    try:
        import openai  # noqa: F401
    except ImportError:
        sys.exit("pip install openai")

    asyncio.run(run(" ".join(sys.argv[1:]) or None))


if __name__ == "__main__":
    main()
