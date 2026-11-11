"""
This is an example tool to demonstrate how to expose an ontology to a text2cypher agent.

The tool reads a document written in the Neo4j Ontology Graph Specification
(https://github.com/neo4j/ontology-graph-spec) and returns a compact "schema card"
of the whole domain, or of a sub-schema covering only the entities the agent asked for.

Compared with the Neo4j MCP server's `get-schema`, this tells the model:
* what each label, relationship type and property means (descriptions, aliases),
* how many relationships each end has (cardinality),
* which values a property may take (`one_of` / `pattern`).

Two sources are supported:
* `source="file"` reads a YAML or JSON ontology file (default: `ontology/movies.ontology.yaml`,
  override with the `ONTOLOGY_FILE` environment variable).
* `source="db"` fetches the ontology persisted in the database itself via
  `CALL db.ontology.get()`. This procedure is planned for Neo4j 2026.12 (self-managed & Aura);
  until your database has it, use `source="file"`, or store the ontology as data in a
  separate database and select sub-schemas with the `entities` parameter.
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from langchain_core.tools import StructuredTool
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

DEFAULT_ONTOLOGY_FILE = Path(__file__).resolve().parent.parent / "ontology" / "movies.ontology.yaml"

DB_SOURCE_UNAVAILABLE_HINT = (
    "The database does not expose db.ontology.get(). Ontology persistence in the DBMS"
    " is planned for Neo4j 2026.12; until then use source='file', pointing ONTOLOGY_FILE"
    " at your ontology document."
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
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
        )
        try:
            with driver.session(database=os.getenv("NEO4J_DATABASE")) as session:
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
    document: dict[str, Any], entities: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Keep only the nodes the agent asked for, plus the relationships between them.

    Parameters
    ----------
    document: dict[str, Any]
        The full ontology document.
    entities: list[str]
        The entity names the agent asked for, matched against ids, labels/types and aliases.

    Returns
    -------
    tuple[dict[str, Any], dict[str, Any]]
        The filtered nodes and relationships.
    """

    nodes = {
        node_id: node
        for node_id, node in document.get("nodes", {}).items()
        if _matches(node_id, node.get("aliases", []), entities)
        or _matches(node.get("label", node_id), node.get("aliases", []), entities)
    }
    node_ids = set(nodes)
    relationships = {
        rel_id: rel
        for rel_id, rel in document.get("relationships", {}).items()
        if _matches(rel_id, rel.get("aliases", []), entities)
        or _matches(rel.get("type", rel_id), rel.get("aliases", []), entities)
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


def get_ontology(
    entities: Optional[list[str]] = None,
    include_properties: bool = True,
    source: str = "file",
) -> dict[str, Any]:
    """
    Get the ontology of the database as a compact schema card: labels, relationship
    types, property types and their meaning (descriptions, aliases, cardinality,
    allowed values). Use this to inform Cypher queries instead of, or alongside,
    the raw database schema.
    """

    document = _load_ontology_document(source)

    if entities:
        nodes, relationships = _select_sub_schema(document, entities)
        if not nodes and not relationships:
            available = sorted(
                [
                    *(n.get("label", nid) for nid, n in document.get("nodes", {}).items()),
                    *(r.get("type", rid) for rid, r in document.get("relationships", {}).items()),
                ]
            )
            return {
                "schema_card": (
                    f"No ontology entities matched {entities}."
                    f" Available labels and relationship types: {', '.join(available)}."
                )
            }
    else:
        nodes = document.get("nodes", {})
        relationships = document.get("relationships", {})

    return {
        "source": source,
        "entities": sorted(
            [
                *(n.get("label", nid) for nid, n in nodes.items()),
                *(r.get("type", rid) for rid, r in relationships.items()),
            ]
        ),
        "schema_card": _render_schema_card(document, nodes, relationships, include_properties),
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
    include_properties: bool = Field(
        default=True,
        description="Whether to include property details, or only labels and relationship types.",
    )
    source: str = Field(
        default="file",
        description=(
            "Where to read the ontology from: 'file' (a YAML or JSON ontology document on disk)"
            " or 'db' (the ontology persisted in the database via db.ontology.get(),"
            " available from Neo4j 2026.12)."
        ),
    )


get_ontology_tool = StructuredTool.from_function(
    func=get_ontology,  #                      -> The function that the tool calls when executed
    # name=...,                              -> this is populated by the function name
    # description=...,                       -> this is populated by the function docstring
    args_schema=GetOntologyInput,  #         -> The input schema for the tool
    return_direct=False,  #                    -> Whether to return the raw result to the user
    # coroutine=...,                          -> An async version of the function
)
