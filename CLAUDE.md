# Project notes

This repository is a fork of [neo4j-field/text2cypher-react-agent-example](https://github.com/neo4j-field/text2cypher-react-agent-example)
reframed around a single idea: **show what an ontology adds to a text2cypher agent, and measure it.**

The upstream example builds a LangGraph ReAct agent on the Neo4j Cypher MCP server plus local
tools. This fork adds a local **ontology tool** on top, and grows into the explanation of why it
helps. Keep `upstream` as a git remote for syncing; the fork's README leads with the benefits.

## Current state

- Branch `ontology-tool` (local, not pushed): the ontology tool and its wiring.
- The ontology is a file (`ontology/movies.ontology.yaml`) written in the
  [Neo4j Ontology Graph Specification](https://github.com/neo4j/ontology-graph-spec) format.
- `tools/get_ontology.py` renders a compact **schema card** (descriptions, aliases, types,
  cardinality, keys) from the ontology, with sub-schema selection via `entities` and optional
  property detail via `include_properties`. `source="db"` is reserved for
  `CALL db.ontology.get()` — ontology persistence in the DBMS is planned for a future Neo4j
  release (2026.12 target, timing TBC). It is not available today; the file source is.
- The tool is wired into `agent.py`, `single_file_agent.py` and `evaluation/main.py`; the
  system prompt tells the agent to prefer it.

## The story: why an ontology on top of `get_neo4j_schema`

`get_neo4j_schema` runs `apoc.meta.schema(sample)` — inferred from data, structural only:
labels, relationship types, property names/types, an `indexed` flag. It does **not** know what
things mean. The ontology adds:

- **Descriptions** — what a label/property means (e.g. `imdbRating` is 0–10, `budget` is USD).
- **Aliases** — "actor" resolves to `Person`; the raw schema has no `Actor` label.
- **Cardinality** — `ACTED_IN` has `min_count: 1` at the Movie end ("every movie has an actor").
- **Allowed values** — `one_of` / `pattern`, which a sample can only observe, not declare.
- **Disambiguation** — `RATED` (User→Movie, 0.5–5) vs `REVIEWED` (Person→Movie, 0–100).

Recommended routing policy (to encode in prompt + tool descriptions): call `get_ontology` first
for schema context; call `get_neo4j_schema` only when the ontology has no match or the question
needs data-dependent facts (actual values, populated properties, counts).

Size: ~40 tokens per entity in the card (~500 tokens for this 13-entity model). Sub-schema
selection keeps a call at ~200–500 tokens regardless of ontology size; the full card becomes a
problem beyond a few hundred entities, which is what the todo items below address.

## Todo

Ontology tool
- [ ] Tighten tool description + prompt: state the routing policy and fallback conditions
      explicitly (currently "instead of, or alongside" is ambiguous).
- [ ] Token budget + index mode: if `entities` is omitted or the card exceeds ~2k tokens,
      return an entity index ("label — one-line description; call again with entities") instead
      of the full card. Cap the "no match, available entities" list.
- [ ] Optional `search` parameter (alias/description matching) for vocabulary mismatch.
- [ ] Skip empty `## Nodes` / `## Relationships` headings in the rendered card.
- [ ] When `db.ontology.get()` ships: verify its output shape (the yield name was assumed),
      test `source="db"`, remove the "planned for 2026.12" caveat.

README / story
- [ ] Rewrite the intro around the ontology benefits, with before/after examples
      (alias resolution, RATED vs REVIEWED, description-driven query writing).
- [ ] Add the card-size table and the "small ontology: preload vs tool" trade-off.
- [ ] Link the upstream project and credit it.

Evidence
- [ ] Run the eval suite with and without `get_ontology`; add the RAGAS comparison to the README.
- [ ] Verify the agent actually calls the tool (check `called_tools` in `evals/output/*/metadata.csv`).

Fork hygiene (audit done — details below)
- [ ] Migrate to current majors: langchain 1.x, langgraph 1.x, langchain-mcp-adapters 0.3.x,
      langchain-openai 1.x, ragas 0.4.x, neo4j driver 6.x, openai 3.x. This is the riskiest
      change (LangChain 1.x moved `create_react_agent` → `create_agent`).
- [ ] Consolidate the duplicate agents: `agent.py` and `single_file_agent.py` are 99% identical
      and have drifted (different MCP server pins). Keep one, import `prompt.py` instead of
      inlining the system prompt, and use `tools/find_movie_recommendations.py` instead of the
      inline copy.
- [ ] Unpin/update the MCP server (`mcp-neo4j-cypher@0.6.0` today; 0.6.0 adds `EXPLAIN`-based
      write detection and `NEO4J_SCHEMA_SAMPLE_SIZE`).
- [ ] Make the model configurable (env var) instead of `openai:gpt-4.1` hardcoded in six places;
      update to a current model. Judge model `gpt-4o-mini` in the eval harness is also old.
- [ ] Fix stale README eval docs: `eval.py` no longer exists (it is `evaluation/main.py`), and
      results now land in `evals/output/eval_run_<timestamp>/`.
- [ ] Add CI: ruff + a smoke test for `get_ontology` (and ideally validate
      `ontology/*.yaml` against `ontology-graph-spec.schema.json`).
- [ ] Reset the CHANGELOG for the fork.

## Conventions

- Run from the repo root: `make run-agent-uv`, `make run-eval-uv`, `make format`.
- Requires `.env` with `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`,
  `NEO4J_DATABASE` (demo defaults in `.env.example`). Optional `ONTOLOGY_FILE`.
- The ontology file is validated against the published JSON Schema; do that before changing it.
