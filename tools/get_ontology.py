"""
This is an example tool to demonstrate how to expose an ontology to a text2cypher agent.

The tool reads a document written in the Neo4j Ontology Graph Specification
(https://github.com/neo4j/ontology-graph-spec) and returns a compact "schema card"
of the whole domain, or of a sub-schema covering only the entities the agent asked for.

Compared with the Neo4j MCP server's `get-schema`, this tells the model:
* what each label, relationship type and property means (descriptions, aliases),
* how many relationships each end has (cardinality),
* which values a property may take (`one_of` / `pattern`).

Routing policy: call this tool FIRST for schema context; fall back to `get-schema` only
when (a) no ontology entity matches (the response lists what is available), or (b) the
question needs data-dependent facts the ontology cannot know (actual values, populated
properties, counts).

If a schema card would exceed `TOKEN_BUDGET` (estimated as `len(text) // 4`), a compact
entity index is returned instead, and the agent is told to call again with `entities`
for the part it needs.

Two sources are supported, chosen with the `ONTOLOGY_SOURCE` environment variable
(a deployment choice, not something the model decides):
* `ONTOLOGY_SOURCE=file` (default) reads a YAML or JSON ontology file
  (default: `ontology/movies.ontology.yaml`, override with `ONTOLOGY_FILE`).
* `ONTOLOGY_SOURCE=db` fetches the ontology persisted in the database itself via
  `CALL db.ontology.get()`. This procedure is planned for a future Neo4j release
  (2026.12 target, timing TBC); until your database has it, use the file source, or
  store the ontology as data in a separate database and select sub-schemas with the
  `entities` parameter.
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from langchain_core.tools import StructuredTool
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

DEFAULT_ONTOLOGY_FILE = Path(__file__).resolve().parent.parent / "ontology" / "movies.ontology.yaml"

# Rough token budget for a schema card (tokens estimated as len(text) // 4). A card above
# this budget is replaced by a one-line-per-entity index, and the agent is told to call
# again with `entities` for the part it needs. Module-level so tests can lower it.
TOKEN_BUDGET = 2000
# Cap on how many entity names are listed when a request matches nothing.
MAX_LISTED_ENTITIES = 20


def _estimate_tokens(text: str) -> int:
    """Estimate the token count of a text, roughly four characters per token."""

    return len(text) // 4


DB_SOURCE_UNAVAILABLE_HINT = (
    "The database does not expose db.ontology.get(). Ontology persistence in the DBMS"
    " is planned for a future Neo4j release; until then set ONTOLOGY_SOURCE=file,"
    " pointing ONTOLOGY_FILE at your ontology document."
)


def _load_ontology_document(source: str) -> dict[str, Any]:
    """
    Load the ontology document from the given source.

    Parameters
    ----------
    source: str
        Either "file" (a YAML or JSON document on disk) or "db" (the ontology
        persisted in the database).

    Returns
    -------
    dict[str, Any]
        The decoded ontology document.
    """

    if source == "file":
        path = Path(os.getenv("ONTOLOGY_FILE", DEFAULT_ONTOLOGY_FILE))
        with open(path, "r") as file:
            return yaml.safe_load(file)

    if source == "db":
        try:
            with (
                GraphDatabase.driver(
                    os.getenv("NEO4J_URI"),
                    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
                ) as driver,
                driver.session(database=os.getenv("NEO4J_DATABASE")) as session,
            ):
                record = session.run("CALL db.ontology.get()").single(strict=True)
        except Exception as error:  # noqa: BLE001 -> surface a helpful message to the model
            raise ValueError(f"{error}. {DB_SOURCE_UNAVAILABLE_HINT}") from error
        # The procedure returns the ontology document as a single string value
        ontology = next(iter(record))
        return yaml.safe_load(ontology if isinstance(ontology, str) else str(ontology))

    raise ValueError(f"Unknown source: {source!r}. Use 'file' or 'db'.")


def _matches(name: str, aliases: list[str], wanted: list[str]) -> bool:
    """
    Check whether a node or relationship is wanted, matching case-insensitively
    against its id, label/type and aliases.

    Parameters
    ----------
    name: str
        The id, label or type of the node or relationship.
    aliases: list[str]
        Its aliases, if any.
    wanted: list[str]
        The entity names the agent asked for.

    Returns
    -------
    bool
        Whether it matches.
    """

    candidates = {name.lower(), *(alias.lower() for alias in aliases)}
    return any(term.lower() in candidates for term in wanted)


def _search_matches(term: str, identifiers: list[str], description: Optional[str]) -> bool:
    """
    Check whether a search term appears (case-insensitively, as a substring) in any of
    an entity's identifiers (id, label/type, aliases) or in its description.

    Parameters
    ----------
    term: str
        The search term the agent provided.
    identifiers: list[str]
        The id, label or type, and aliases of the node or relationship.
    description: Optional[str]
        Its description, if any.

    Returns
    -------
    bool
        Whether it matches.
    """

    needle = term.lower()
    return any(needle in identifier.lower() for identifier in identifiers) or (
        description is not None and needle in description.lower()
    )


def _one_line(text: Optional[str]) -> str:
    """
    Flatten a description onto a single line, truncated for the entity index.

    Parameters
    ----------
    text: Optional[str]
        The description, if any.

    Returns
    -------
    str
        A single-line version, at most 100 characters.
    """

    if not text:
        return ""
    line = " ".join(text.split())
    return line if len(line) <= 100 else f"{line[:97]}..."


def _cardinality(end: dict[str, Any]) -> str:
    """
    Describe the cardinality of one end of a relationship, e.g. "min 1 at Movie end".

    Parameters
    ----------
    end: dict[str, Any]
        The `from` or `to` end of a relationship mapping.

    Returns
    -------
    str
        The cardinality description.
    """

    if "count" in end:
        return f"exactly {end['count']}"
    parts = []
    if "min_count" in end:
        parts.append(f"min {end['min_count']}")
    if "max_count" in end:
        parts.append(f"max {end['max_count']}")
    return ", ".join(parts) if parts else "any"


def _describe_property(name: str, prop: dict[str, Any]) -> str:
    """
    Describe one property on a single line, e.g. "title: STRING (key) - Film title.".

    Parameters
    ----------
    name: str
        The id of the property.
    prop: dict[str, Any]
        The property mapping.

    Returns
    -------
    str
        The property description.
    """

    annotations = [
        annotation
        for flag, annotation in (
            (prop.get("key"), "key"),
            (prop.get("unique"), "unique"),
            (prop.get("must_exist"), "must_exist"),
        )
        if flag
    ]
    suffix = f" ({', '.join(annotations)})" if annotations else ""
    description = f" - {prop['description']}" if prop.get("description") else ""
    return f"- {name}: {prop.get('type', 'ANY')}{suffix}{description}"


def _select_sub_schema(
    document: dict[str, Any],
    entities: Optional[list[str]],
    search: Optional[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Keep only the entities the agent asked for, plus the relationships between the
    selected nodes.

    `entities` matches exactly (case-insensitively) against ids, labels/types and
    aliases; `search` matches as a substring against those and descriptions. If both
    are given, an entity must match both. A relationship is kept if it matches either
    filter itself, or if both its endpoints are selected nodes.

    Parameters
    ----------
    document: dict[str, Any]
        The full ontology document.
    entities: Optional[list[str]]
        The entity names the agent asked for, or None for no filtering.
    search: Optional[str]
        The search term the agent provided, or None for no filtering.

    Returns
    -------
    tuple[dict[str, Any], dict[str, Any]]
        The filtered nodes and relationships.
    """

    def node_selected(node_id: str, node: dict[str, Any]) -> bool:
        aliases = node.get("aliases", [])
        label = node.get("label", node_id)
        if entities and not (
            _matches(node_id, aliases, entities) or _matches(label, aliases, entities)
        ):
            return False
        return not search or _search_matches(
            search, [node_id, label, *aliases], node.get("description")
        )

    def rel_selected(rel_id: str, rel: dict[str, Any]) -> bool:
        aliases = rel.get("aliases", [])
        rel_type = rel.get("type", rel_id)
        if entities and not (
            _matches(rel_id, aliases, entities) or _matches(rel_type, aliases, entities)
        ):
            return False
        return not search or _search_matches(
            search, [rel_id, rel_type, *aliases], rel.get("description")
        )

    nodes = {
        node_id: node
        for node_id, node in document.get("nodes", {}).items()
        if node_selected(node_id, node)
    }
    node_ids = set(nodes)
    relationships = {
        rel_id: rel
        for rel_id, rel in document.get("relationships", {}).items()
        if rel_selected(rel_id, rel)
        or rel.get("from", {}).get("node") in node_ids
        and rel.get("to", {}).get("node") in node_ids
    }
    return nodes, relationships


def _render_schema_card(
    document: dict[str, Any],
    nodes: dict[str, Any],
    relationships: dict[str, Any],
    include_properties: bool,
) -> str:
    """
    Render a compact, human- and model-readable schema card of a (sub-)schema.

    Parameters
    ----------
    document: dict[str, Any]
        The full ontology document, for the model's name and description.
    nodes: dict[str, Any]
        The nodes to include.
    relationships: dict[str, Any]
        The relationships to include.
    include_properties: bool
        Whether to list properties, or only labels and relationship types.

    Returns
    -------
    str
        The schema card as Markdown.
    """

    lines = [f"# {document.get('name', document.get('id', 'Ontology'))} ontology"]
    if document.get("description"):
        lines.append(document["description"])

    if nodes:
        lines.append("\n## Nodes")
    for node_id, node in nodes.items():
        label = node.get("label", node_id)
        aliases = f" (aliases: {', '.join(node['aliases'])})" if node.get("aliases") else ""
        lines.append(f"\n### {label}{aliases}")
        if node.get("description"):
            lines.append(f"{node['description']}")
        if include_properties and node.get("properties"):
            lines.append("Properties:")
            lines.extend(
                _describe_property(prop_id, prop) for prop_id, prop in node["properties"].items()
            )

    if relationships:
        lines.append("\n## Relationships")
    for rel_id, rel in relationships.items():
        rel_type = rel.get("type", rel_id)
        from_label = rel.get("from", {}).get("label", "?")
        to_label = rel.get("to", {}).get("label", "?")
        lines.append(f"\n### {from_label} -[{rel_type}]-> {to_label}")
        if rel.get("description"):
            lines.append(f"{rel['description']}")
        cardinality = (
            f"{_cardinality(rel['from'])} at {from_label} end,"
            f" {_cardinality(rel['to'])} at {to_label} end"
        )
        lines.append(f"Cardinality: {cardinality}")
        if include_properties and rel.get("properties"):
            lines.append("Properties:")
            lines.extend(
                _describe_property(prop_id, prop) for prop_id, prop in rel["properties"].items()
            )

    return "\n".join(lines)


def _render_entity_index(
    document: dict[str, Any],
    nodes: dict[str, Any],
    relationships: dict[str, Any],
) -> str:
    """
    Render a compact entity index (one line per entity) instead of a schema card that
    would exceed the token budget, telling the agent to call again with `entities`.

    Parameters
    ----------
    document: dict[str, Any]
        The full ontology document, for the model's name.
    nodes: dict[str, Any]
        The nodes to include.
    relationships: dict[str, Any]
        The relationships to include.

    Returns
    -------
    str
        The entity index as Markdown.
    """

    lines = [f"# {document.get('name', document.get('id', 'Ontology'))} ontology (entity index)"]
    if nodes:
        lines.append("\n## Nodes")
        lines.extend(
            f"- {node.get('label', node_id)} — {_one_line(node.get('description'))}"
            for node_id, node in nodes.items()
        )
    if relationships:
        lines.append("\n## Relationships")
        lines.extend(
            f"- {rel.get('type', rel_id)} — {_one_line(rel.get('description'))}"
            for rel_id, rel in relationships.items()
        )
    lines.append("\nCall again with entities=[...] to get the full card for the entities you need.")
    return "\n".join(lines)


def _entity_names(nodes: dict[str, Any], relationships: dict[str, Any]) -> list[str]:
    """
    List the labels and relationship types of a (sub-)schema, sorted.

    Parameters
    ----------
    nodes: dict[str, Any]
        The nodes, keyed by id.
    relationships: dict[str, Any]
        The relationships, keyed by id.

    Returns
    -------
    list[str]
        The entity names.
    """

    return sorted(
        [
            *(n.get("label", nid) for nid, n in nodes.items()),
            *(r.get("type", rid) for rid, r in relationships.items()),
        ]
    )


def get_ontology(
    entities: Optional[list[str]] = None,
    search: Optional[str] = None,
    include_properties: bool = True,
) -> dict[str, Any]:
    """
    Get the ontology of the database as a compact schema card: labels, relationship
    types, property types and their meaning (descriptions, aliases, cardinality,
    allowed values).

    Call this FIRST for schema context, before `get-schema`. Fall back to `get-schema`
    only when (a) no ontology entity matches — the response lists what is available —
    or (b) the question needs data-dependent facts the ontology cannot know (actual
    values, populated properties, counts).

    If the card would exceed the token budget, an entity index is returned instead;
    call again with `entities` to get the full cards for the entities you need.
    """

    document = _load_ontology_document(os.getenv("ONTOLOGY_SOURCE", "file"))
    nodes, relationships = _select_sub_schema(document, entities, search)

    if not nodes and not relationships and (entities or search):
        what = f"entities {entities}" if entities else f"search {search!r}"
        available = _entity_names(document.get("nodes", {}), document.get("relationships", {}))
        if len(available) > MAX_LISTED_ENTITIES:
            available = [
                *available[:MAX_LISTED_ENTITIES],
                f"... and {len(available) - MAX_LISTED_ENTITIES} more",
            ]
        return {
            "schema_card": (
                f"No ontology entities matched {what}. Available labels and relationship"
                f" types: {', '.join(available)}."
            )
        }

    card = _render_schema_card(document, nodes, relationships, include_properties)
    entity_names = _entity_names(nodes, relationships)
    if _estimate_tokens(card) > TOKEN_BUDGET:
        return {
            "entities": entity_names,
            "schema_card": _render_entity_index(document, nodes, relationships),
        }
    return {
        "entities": entity_names,
        "schema_card": card,
    }


class GetOntologyInput(BaseModel):
    entities: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional entity names to build a sub-schema card from, matched against labels,"
            " relationship types and their aliases (e.g. ['Movie', 'Actor', 'RATED'])."
            " Omit to get the whole ontology."
        ),
    )
    search: Optional[str] = Field(
        default=None,
        description=(
            "Optional case-insensitive search term, matched as a substring against labels,"
            " relationship types, aliases and descriptions (e.g. 'performer' resolves to"
            " Person). Returns cards for matching entities only."
        ),
    )
    include_properties: bool = Field(
        default=True,
        description="Whether to include property details, or only labels and relationship types.",
    )


get_ontology_tool = StructuredTool.from_function(
    func=get_ontology,  #                      -> The function that the tool calls when executed
    # name=...,                              -> this is populated by the function name
    # description=...,                       -> this is populated by the function docstring
    args_schema=GetOntologyInput,  #         -> The input schema for the tool
    return_direct=False,  #                    -> Whether to return the raw result to the user
    # coroutine=...,                          -> An async version of the function
)
