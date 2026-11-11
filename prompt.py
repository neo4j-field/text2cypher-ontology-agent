import os

ONTOLOGY_INSTRUCTION = (
    "* Call `get_ontology` FIRST for schema context: it tells you what labels, "
    "relationship types and properties mean (descriptions, aliases, cardinality, "
    "allowed values), which `get-schema` does not. Pass `entities` to get only the "
    "relevant part of the ontology, or `search` to resolve vocabulary to entities. "
    "Fall back to `get-schema` only when the ontology has no matching entity (its "
    "response lists what is available) or when the question needs data-dependent "
    "facts the ontology cannot know: actual values, populated properties, counts."
)

SCHEMA_INSTRUCTION = (
    "* Use the `get-schema` tool to retrieve the data model schema before writing queries."
)


def ontology_enabled() -> bool:
    """
    Whether the ontology tool is exposed to the agent.

    Controlled by `WITH_ONTOLOGY`; enabled by default. The evaluation harness
    uses this to run the same questions with and without the ontology.

    Returns
    -------
    bool
        Whether to expose the ontology tool.
    """

    return os.getenv("WITH_ONTOLOGY", "true").strip().lower() not in {"false", "0", "no"}


def get_movies_system_prompt(include_ontology: bool = True) -> str:
    """
    Get the system prompt for the movies agent.

    Parameters
    ----------
    include_ontology : bool
        Whether to instruct the agent to prefer the ontology tool. When false,
        the prompt falls back to the raw schema tool, giving a fair baseline.

    Returns
    -------
    str
        The system prompt for the movies agent.
    """

    schema_instruction = ONTOLOGY_INSTRUCTION if include_ontology else SCHEMA_INSTRUCTION
    return f"""You are a Neo4j expert that knows how to write Cypher queries to address movie questions.
As a Cypher expert, when writing queries:
* You must always ensure you have the data model schema to inform your queries
{schema_instruction}
* If an error is returned from the database, you may refactor your query or ask the user to provide additional information
* If an empty result is returned, use your best judgement to determine if the query is correct.
* Use `variable.property IS NOT NULL` to check property existence.

If using a tool that does NOT require writing a Cypher query, you do not need the database schema.

As a well respected movie expert:
* Ensure that you provide detailed responses with citations to the underlying data"""
