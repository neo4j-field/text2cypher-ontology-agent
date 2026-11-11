# Ontology-Aware Text2Cypher Agent

A template for building a [Text2Cypher](https://graphrag.com/reference/graphrag/text2cypher/)
ReAct agent with the [official Neo4j MCP Server](https://github.com/neo4j/mcp), local tools,
and an optional **domain ontology tool**. Built with LangGraph; the demo connects to the
Neo4j Movies database and answers movie questions in natural language.

On top of the schema that `get-schema` infers from the data, the ontology tool tells the agent
what things *mean*:

| The model needs to know | `get-schema` | Ontology |
|---|---|---|
| Is `budget` in dollars? Is `imdbRating` 0–10 or 0–100? | ❌ just `INTEGER` / `FLOAT` | ✅ "Production budget in US dollars", "0.0 to 10.0" |
| The user says "performer" — which label is that? | ❌ silently matches nothing | ✅ alias → `Person` |
| How is a title with "The" stored? | ❌ | ✅ "`Title, The`" |

The full story — how the tool works, card sizes, pros and cons, and how to adapt it to your
domain — is in [docs/ontology.md](docs/ontology.md).

## Repository structure

- [single_file_agent.py](single_file_agent.py) — the agent, as a heavily commented walkthrough
  (custom tools, MCP server wiring, the ontology tool, the chat loop). Start here.
- [tools/get_ontology.py](tools/get_ontology.py) — the ontology tool
- [ontology/movies.ontology.yaml](ontology/movies.ontology.yaml) — the example ontology
  ([Neo4j Ontology Graph Specification](https://github.com/neo4j/ontology-graph-spec) format)
- [prompt.py](prompt.py) — the system prompt, with/without ontology instructions
- [questions.yaml](questions.yaml) — eval questions and reference answers
- [evaluation/](evaluation/main.py) — the RAGAS evaluation harness
- [docs/ontology.md](docs/ontology.md), [docs/evaluation.md](docs/evaluation.md) — deep dives

## Prerequisites

- Python 3.11 or higher
- `uv` (required even if you install with pip — it installs the dependencies and runs the
  Neo4j MCP server via `uvx`)
- Neo4j Aura account or local Neo4j instance with the Movies database (the demo credentials
  in `.env.example` work out of the box — see [Configuration](#configuration))
- OpenAI API key

## Installation

### Option 1: Using uv (recommended)

1. **Install uv** (if not already installed):
   [Install Documentation](https://docs.astral.sh/uv/getting-started/installation/)

2. **Clone and setup the project**:
   ```bash
   git clone https://github.com/neo4j-field/text2cypher-ontology-agent.git
   cd text2cypher-ontology-agent
   ```

3. **Install dependencies**:
   ```bash
   uv sync
   ```

### Option 2: Using pip

1. Clone as above, then create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

   Note: `uv` is still required on this path — the agent launches the Neo4j MCP server with
   `uvx` at runtime (`pip install uv`), or adapt `mcp_server.py` to run the server another way.

## Configuration

1. **Copy the example environment file**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your credentials** (`OPENAI_API_KEY` plus your `NEO4J_*` values).

   **Works out of the box:** `.env.example` ships working credentials for the public
   `recommendations` demo database (demo.neo4jlabs.com), so `cp .env.example .env` plus your
   OpenAI key is enough to run the agent immediately. If you point at your own instance
   instead, note that the evaluation questions (`questions.yaml`) assume the
   *recommendations* dataset — User ratings, production budgets — which a plain
   `:play movies` graph does not have: load the recommendations dataset, or write your own
   questions for your own data.

## Running the agent

```bash
make run-agent-uv
# or
uv run python3 single_file_agent.py
```

Ask questions like *"What movies are in the database?"*, *"Tell me about The Matrix"*, or
*"Recommend me some films like The Dark Knight."* Exit with `exit`, `quit` or `q`.

## Measuring what the ontology changes

The evaluation harness runs the same questions with the ontology tool on and off
(`WITH_ONTOLOGY=true|false` in `.env`) and scores the answers with RAGAS metrics. On our
benchmark the answers are roughly the same with and without the ontology; what differs is the
path to the answer — the ontology agent asks fewer follow-up queries because it does not have
to discover units, aliases and storage conventions by sampling the data.

How to run it, what the metrics mean (and their caveats), and the output layout:
[docs/evaluation.md](docs/evaluation.md).

## Development

```bash
make format                        # ruff format + lint
uv run python tests/smoke_test.py  # offline checks of the ontology tool + YAML validation
```

The smoke test runs with no database or API key and validates the ontology against the
published JSON Schema — the pattern to copy for validating your own ontology file.
CI (`.github/workflows/ci.yml`) runs ruff and the smoke test on every push.

## Troubleshooting

- **Connection issues** — verify your Neo4j credentials in `.env` and that the instance is
  reachable.
- **OpenAI issues** — verify your API key and usage limits.
- **MCP server issues** — the agent installs the official `neo4j-mcp-server` via `uvx` at
  startup; make sure `uvx` is on your PATH.

## Credits

This repository is a fork of
[neo4j-field/text2cypher-react-agent-example](https://github.com/neo4j-field/text2cypher-react-agent-example)
by the Neo4j Field team — the agent skeleton, the evaluation harness and the recommendation
tool come from there. The ontology tool, the ontology-aware prompt and the A/B evaluation
setup were added in this fork.

## License

This project is provided as an example for educational and demonstration purposes.
