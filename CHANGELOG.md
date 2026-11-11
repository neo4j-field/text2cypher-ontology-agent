# Changelog

This repository is a fork of
[neo4j-field/text2cypher-react-agent-example](https://github.com/neo4j-field/text2cypher-react-agent-example),
reframed as a template for showing what a domain ontology adds to a text2cypher agent.
History prior to the fork lives in the upstream repository.

## Unreleased (2026-11-11)

### Added
- `get_ontology` tool rendering a compact schema card (descriptions, aliases, types,
  cardinality, keys) from `ontology/movies.ontology.yaml`, written in the
  [Neo4j Ontology Graph Specification](https://github.com/neo4j/ontology-graph-spec) format,
  with sub-schema selection via the `entities` parameter.
- `WITH_ONTOLOGY` switch for A/B evaluation, plus 6 ontology-targeted eval questions
  (16 total).

### Changed
- Switched to the official Neo4j MCP server (`neo4j/mcp`, pinned to
  `neo4j-mcp-server@2.1.1` via uvx), read-only, tools filtered to `get-schema` and
  `read-cypher`, replacing the Labs `mcp-neo4j-cypher` server.
- Made models configurable via environment variables (`OPENAI_MODEL`,
  `OPENAI_REASONING_EFFORT`, `JUDGE_MODEL`) in `llm.py`; the judge uses reasoning where
  the model supports it.
- Migrated to current library majors: langchain 1.5, langgraph 1.2,
  langchain-mcp-adapters 0.3.2, langchain-openai 1.7.4, ragas 0.4.3, neo4j 6.4.1,
  openai 3.3.0 (Python >= 3.11); `create_react_agent` -> `create_agent`, and
  `pre_model_hook` -> an async `trim_history` middleware.
- Consolidated the duplicate agents into a single, commented `single_file_agent.py`
  entry point.
- Rewrote the README around the ontology story, with an honest "what we measured"
  section and pros/cons.

### Fixed
- Rewrote the ontology file to be faithful to the demo database: removed invented
  relationships (`REVIEWED`, `PRODUCED`, `WROTE`, `FOLLOWS`) and corrected
  cardinalities and property types verified against the data.
