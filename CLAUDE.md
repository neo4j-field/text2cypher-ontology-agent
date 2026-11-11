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
- The tool is wired into `single_file_agent.py` and `evaluation/main.py`; the system prompt
  tells the agent to prefer it.

## The story: why an ontology on top of `get-schema`

`get-schema` (the official Neo4j MCP server's schema tool) is inferred from a data sample,
structural only: labels, relationship types, property names/types, an `indexed` flag. It does
**not** know what things mean. The ontology adds:

- **Descriptions** — what a label/property means (e.g. `imdbRating` is 0–10, `budget` is USD,
  `RATED.rating` is 0.5–5 half-stars, `RATED.timestamp` is Unix epoch seconds).
- **Aliases** — "performer"/"filmmaker" resolve to `Person` (note: the demo DB *does* have
  `Actor`/`Director` as secondary labels on `Person`, so the alias win is vocabulary, not label
  discovery).
- **Cardinality** — `IN_GENRE` has `min_count: 1` at the Genre end, verified true in the data.
- **Allowed values** — `one_of` / `pattern`, which a sample can only observe, not declare.
- **Format conventions** — titles beginning with "The" are stored as `Title, The`.

**Ontology faithfulness (fixed 2026-11-11):** the first draft declared `REVIEWED`, `PRODUCED`,
`WROTE`, `FOLLOWS` (none exist in this dataset) and `min_count: 1` for `ACTED_IN`/`DIRECTED`
at the Movie end (false: 41 movies have no actor, 55 no director), and used `roles` LIST and
`datetime` where the data has `role` STRING and `timestamp` INTEGER epoch. All corrected after
verifying against the DB — an ontology that invents structure misleads the agent.

Recommended routing policy (to encode in prompt + tool descriptions): call `get_ontology` first
for schema context; call `get-schema` only when the ontology has no match or the question
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
- [x] Benefits section in the README with the comparison table and concrete examples
      (alias resolution, RATED vs REVIEWED, cardinality, governed artifact), routing policy,
      and a sample card.
- [x] Plain-language **pros and cons** section in the README (2026-11-11), explicitly noting
      that not every benefit is measured by this example's eval — it is template code.
- [ ] Add the card-size table and the "small ontology: preload vs tool" trade-off.
- [ ] Link the upstream project and credit it.

Evidence
- [x] Add a `WITH_ONTOLOGY` switch (`prompt.py`) and run both conditions
      (`evals/output/eval_run_*/`). First run was **inconclusive**: on 10 questions the ontology
      condition scored lower on factual correctness (0.246 vs 0.318) and higher on answer
      relevancy (0.738 vs 0.630). Diagnostics: (1) n=10 and single-run noise, (2) the question
      set does not test any claimed ontology advantage (aliases, RATED vs REVIEWED, cardinality,
      allowed values), (3) three questions are out-of-scope and dominate score variance.
- [x] Verify the agent actually calls the tool: `get_ontology` appears in `called_tools` for
      10/10 questions; the baseline uses `get-schema` instead.
- [x] Added 6 ontology-targeted questions (16 total) and ran both conditions
      (2026-11-11 runs at 15:41 ontology / 15:43 baseline). Result: **accuracy is not
      discriminating** — gpt-6-luna answers the questions correctly from the raw schema too,
      and `FactualCorrectness` is too noisy (it scores identical correct answers 0.0 on both
      sides because ragas checks each answer claim against the reference in isolation, so
      paraphrases that name the subject fail). What *does* separate the conditions is effort:
      on the 6 ontology-focused questions the ontology run needed 2.0 tool calls and 3.0 LLM
      calls per question averaging 8.1 s, the baseline 2.8 / 3.8 and 18.8 s — the baseline
      spends extra `read-cypher` probes discovering title format and the actor relationship.
      Lead the README evidence with tool calls / latency, and keep accuracy with a noise caveat.
      Framing decision (user, 2026-11-11): this fork is **template code** for customers who want
      an ontology — it is fine and preferred to say there is not a lot of difference with/without
      it. Do not overclaim benefits; keep the repo simple.
- [x] Repeated the A/B pair (2 runs per condition, 2026-11-11). Ontology numbers are
      reproducible: on the 6 focus questions 2.00 tool calls / 3.00 LLM calls / 8.0 s vs the
      baseline's 2.83 / 3.83 / 20.9 s. Accuracy stays roughly equal (rouge 0.355 vs 0.343,
      relevancy 0.768 vs 0.773, factual 0.273 vs 0.339 but judge-noisy — not led with).
      README now carries these numbers with the honest template-code framing.

Fork hygiene (audit done — details below)
- [x] Migrated to current majors (2026-11-11): langchain 1.5, langgraph 1.2,
      langchain-mcp-adapters 0.3.2, langchain-openai 1.7.4, ragas 0.4.3, neo4j 6.4.1,
      openai 3.3.0 (ragas 0.4.3 caps `openai<3.49` via `instructor`), mcp 1.27.
      `requires-python` raised to `>=3.11` (langchain 1.x requirement).
      `create_react_agent` → `create_agent`; `prompt=` → `system_prompt=`; the
      `pre_model_hook` is now an async `trim_history` middleware (`@wrap_model_call`).
      Regression checked by the 16-question eval: both conditions 16/16, no errors, focus
      effort unchanged (ontology 2.00 calls / 8.1 s vs baseline 2.67 / 24.1 s).
- [x] Consolidated to a single agent file (2026-11-11): `agent.py` was removed and
      `single_file_agent.py` is now the only entry point — a heavily commented walkthrough
      of the model, the inline custom tool, the MCP server wiring, the ontology tool and the
      chat loop. `evaluation/main.py` builds its own agent; `tools/find_movie_recommendations.py`
      remains for reuse by the eval.
- [x] Switch to the official Neo4j MCP server (`neo4j/mcp`, Go, product-supported): pinned to
      `neo4j-mcp-server@2.1.1` via uvx in `mcp_server.py`, read-only, tools filtered to
      `get-schema,read-cypher`. Replaces the Labs `mcp-neo4j-cypher` server, whose `0.3.0`
      pin no longer starts (it imports `fastmcp.tools.tool`, removed in current fastmcp) and
      whose README now redirects to the official server.
- [x] Make the model configurable (`llm.py`: `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`,
      `JUDGE_MODEL`). Agent defaults to `gpt-6-luna`; judge to `gpt-6-sol`. Both use the
      Responses API for tool calling. `message_text()` in `utils.py` flattens Responses API
      content blocks before writing CSV / scoring.
      Known constraint: ragas 0.3.9 cannot parse decimal model versions (`gpt-6.1-terra`)
      and its structured-output path uses Chat Completions function tools, which GPT-6 models
      only allow with `reasoning_effort="none"`. Revisit when ragas is upgraded.
      Also fixed 2026-11-11: ragas 0.3.x `AnswerRelevancy.ascore` embeds through a sync call;
      with an `AsyncOpenAI` client it bridges via a new thread and blocks the event loop on
      `Thread.join` → the eval deadlocks (observed with 16 concurrent questions). The 0.3
      workaround (sync `OpenAI()` client) is obsolete after the 0.4 migration: ragas 0.4
      calls `aembed_text()` and requires the async client again
      (`evaluation/components/agent.py`).
- [x] Fixed stale README eval docs (2026-11-11): points at `evaluation/main.py`, documents
      env-driven config, and the `evals/output/eval_run_<timestamp>_<condition>/` layout.
- [ ] Add CI: ruff + a smoke test for `get_ontology` (and ideally validate
      `ontology/*.yaml` against `ontology-graph-spec.schema.json`).
- [ ] Reset the CHANGELOG for the fork.

## Conventions

- Run from the repo root: `make run-agent-uv`, `make run-eval-uv`, `make format`.
- Requires `.env` with `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`,
  `NEO4J_DATABASE` (demo defaults in `.env.example`). Optional `ONTOLOGY_FILE`.
- The ontology file is validated against the published JSON Schema; do that before changing it.
