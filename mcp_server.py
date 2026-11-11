"""Connection parameters for the official Neo4j MCP server."""

import os

from mcp import StdioServerParameters

# Official, product-supported Neo4j MCP server (Go), replacing the Neo4j Labs
# `mcp-neo4j-cypher` server this example originally used.
# https://github.com/neo4j/mcp
NEO4J_MCP_SERVER_VERSION = "2.1.1"

# Only expose the schema and read tools. `--read-only` already hides write-cypher;
# the explicit tool filter keeps the tool surface (and its token cost) small.
ALLOWED_MCP_TOOLS = {"get-schema", "read-cypher"}


def get_neo4j_mcp_server() -> StdioServerParameters:
    """
    Build the stdio parameters for the official Neo4j MCP server.

    The server expects `NEO4J_MCP_*` variables; the project's `.env` keeps the
    usual `NEO4J_*` names, so translate them here. Read at call time (not import
    time) so values from `.env` are available.

    Returns
    -------
    StdioServerParameters
        The parameters to pass to `stdio_client`.
    """

    return StdioServerParameters(
        command="uvx",
        args=[
            f"neo4j-mcp-server@{NEO4J_MCP_SERVER_VERSION}",
            "--transport-mode",
            "stdio",
            "--read-only",
            "true",
            "--tools",
            ",".join(sorted(ALLOWED_MCP_TOOLS)),
        ],
        env={
            "NEO4J_MCP_URI": os.getenv("NEO4J_URI"),
            "NEO4J_MCP_USERNAME": os.getenv("NEO4J_USERNAME"),
            "NEO4J_MCP_PASSWORD": os.getenv("NEO4J_PASSWORD"),
            "NEO4J_MCP_DATABASE": os.getenv("NEO4J_DATABASE"),
        },
    )
