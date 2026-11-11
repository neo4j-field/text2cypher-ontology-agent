"""A Text2Cypher agent in a single file.

This file walks through everything needed to build a ReAct-style agent that
answers questions about the Neo4j Movies database:

1. The chat model
2. A custom local tool (a plain Python function the agent can call)
3. The Neo4j MCP server (schema + read-only Cypher, via the Model Context Protocol)
4. The optional ontology tool
5. The agent itself, plus an interactive chat loop

Run it with `uv run python3 single_file_agent.py` (or `make run-agent-uv`).
"""

import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.checkpoint.memory import InMemorySaver
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from neo4j import GraphDatabase, RoutingControl
from pydantic import BaseModel, Field

from llm import build_agent_model
from mcp_server import ALLOWED_MCP_TOOLS, get_neo4j_mcp_server
from prompt import get_movies_system_prompt, ontology_enabled
from tools.get_ontology import get_ontology_tool
from utils import print_astream, trim_history

# Load Neo4j credentials and the OpenAI API key from .env
if load_dotenv():
    print("Loaded .env file")
else:
    print("No .env file found")


# ---------------------------------------------------------------------------
# 1. A custom local tool
# ---------------------------------------------------------------------------
# Tools are how the agent acts on the world. Besides the Cypher tools from the
# MCP server, the agent can call ordinary Python functions. A tool has:
#
# * a function that runs when the tool is called,
# * a description (from its docstring) telling the model WHEN to use it,
# * a pydantic model describing its arguments, so the model knows HOW to call it.
#
# This one recommends movies: it finds films rated highly by the same users who
# loved a given movie.


def find_movie_recommendations(
    movie_title: str, min_user_rating: float = 4.0, limit: int = 10
) -> list[dict[str, Any]]:
    """Search the database for movie recommendations based on a movie title."""

    query = """
MATCH (target:Movie)
WHERE target.title = $movieTitle
MATCH (target)<-[r1:RATED]-(u:User)
WHERE r1.rating >= $minRating
MATCH (u)-[r2:RATED]->(similar:Movie)
WHERE similar <> target
  AND r2.rating >= $minRating
  AND similar.imdbRating IS NOT NULL
WITH similar, count(*) AS supporters, avg(r2.rating) AS avgRating
WHERE supporters >= 10
RETURN similar.title, similar.year, similar.imdbRating,
       supporters AS people_who_loved_both,
       round(avgRating, 2) AS avg_rating_by_target_lovers
ORDER BY supporters DESC, avgRating DESC
LIMIT $limit
    """

    # A plain (synchronous) Neo4j driver call. The tool is executed in a worker
    # thread by the agent, so blocking here is fine.
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    return driver.execute_query(
        query,
        parameters_={"movieTitle": movie_title, "minRating": min_user_rating, "limit": limit},
        database_=os.getenv("NEO4J_DATABASE"),
        routing_=RoutingControl.READ,
        result_transformer_=lambda r: r.data(),
    )


class FindMovieRecommendationsInput(BaseModel):
    """The arguments the model must provide when it calls the tool."""

    movie_title: str = Field(
        ...,
        description=(
            "The title of the movie to find recommendations for. If it begins "
            "with 'The', use the format 'Title, The'."
        ),
    )
    min_user_rating: float = Field(
        default=4.0,
        description="The minimum rating (0.5 to 5.0) a user must give a movie.",
        ge=0.5,
        le=5.0,
    )
    limit: int = Field(
        default=10,
        description="The maximum number of recommendations to return.",
        ge=1,
    )


find_movie_recommendations_tool = StructuredTool.from_function(
    func=find_movie_recommendations,  # -> The function that runs when the tool is called
    # name=...,                       # -> Defaults to the function name
    # description=...,                # -> Defaults to the function docstring
    args_schema=FindMovieRecommendationsInput,  # -> The tool's input schema
    return_direct=False,  #                        -> False: give the result back to the model
)


# ---------------------------------------------------------------------------
# 2. The agent
# ---------------------------------------------------------------------------


async def main():
    """Start the MCP server, build the agent with all its tools, and chat."""

    # -----------------------------------------------------------------------
    # 2a. The Neo4j MCP server
    # -----------------------------------------------------------------------
    # The official Neo4j MCP server (https://github.com/neo4j/mcp) is a small
    # Go process that exposes tools to run schema introspection (`get-schema`)
    # and read-only Cypher (`read-cypher`) against our database.
    #
    # `stdio_client` starts the server as a subprocess and gives us a pair of
    # streams to talk to it; `ClientSession` speaks the MCP protocol over them.
    # `mcp_server.py` holds the server configuration (version pin, env vars,
    # read-only flag and the tool allow-list).
    async with stdio_client(get_neo4j_mcp_server()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()  # Handshake with the MCP server

            # Turn the MCP tools into LangChain tools the agent can call
            mcp_tools = await load_mcp_tools(session)

            # Keep only the two tools we want to expose
            allowed_tools = [tool for tool in mcp_tools if tool.name in ALLOWED_MCP_TOOLS]

            # -----------------------------------------------------------------
            # 2b. Put all the tools together
            # -----------------------------------------------------------------
            allowed_tools.append(find_movie_recommendations_tool)

            # The ontology tool is optional: it returns a compact description of
            # what the labels, relationships and properties MEAN (units, scales,
            # aliases), which `get-schema` cannot. Set WITH_ONTOLOGY=false in
            # .env to run the agent without it.
            if ontology_enabled():
                allowed_tools.append(get_ontology_tool)

            # -----------------------------------------------------------------
            # 2c. Create the agent
            # -----------------------------------------------------------------
            # `create_agent` builds the reason/act loop: the model decides which
            # tools to call, the agent runs them and feeds the results back,
            # until the model produces a final answer.
            agent = create_agent(
                build_agent_model(),  #          -> The chat model (OPENAI_MODEL in .env)
                allowed_tools,  #                -> The tools listed above
                middleware=[trim_history],  #    -> Trims old messages before each model call
                checkpointer=InMemorySaver(),  # -> Keeps conversation history between turns
                system_prompt=get_movies_system_prompt(ontology_enabled()),  # -> Instructions
            )

            # -----------------------------------------------------------------
            # 2d. Chat loop
            # -----------------------------------------------------------------
            # Each user message is passed to the agent. The same `thread_id` in
            # CONFIG lets the checkpointer keep the conversation going across
            # turns. `stream_mode="updates"` reports every intermediate step
            # (model text, tool calls, tool results) as it happens.
            print("\n===================================== Chat =====================================\n")

            while True:
                user_input = input("> ")
                if user_input.lower() in {"exit", "quit", "q"}:
                    break

                await print_astream(
                    agent.astream(
                        {"messages": user_input},
                        config={"configurable": {"thread_id": "1"}},
                        stream_mode="updates",
                    )
                )


if __name__ == "__main__":
    asyncio.run(main())
