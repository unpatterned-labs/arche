"""The MCP server: arche's verbs as tools an agent runtime can call.

Needs the ``mcp`` extra (``pip install "arche-core[mcp]"``). Run it with
``arche mcp`` (stdio, the default) or ``arche mcp --transport streamable-http``
for a network client. :mod:`arche.mcp.handlers` is the plain-Python surface;
:mod:`arche.mcp.server` registers it with the MCP SDK.

Importing this package does not import the SDK; ``arche.mcp.server`` does.
"""
