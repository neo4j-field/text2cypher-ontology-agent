# Ontology-Aware Text2Cypher Agent

This repo is a template for building a [Text2Cypher](https://graphrag.com/reference/graphrag/text2cypher/) ReAct agent with the [official Neo4j MCP Server](https://github.com/neo4j/mcp), local tools, and an optional **domain ontology tool**.

A conversational AI agent that connects to a Neo4j Movies database and can answer movie-related questions using natural language. Built with LangGraph's implementation of a ReAct agent, the official Neo4j MCP server, and a custom movie recommendations tool.

A conversational AI agent that connects to a Neo4j Movies database and can answer movie-related questions using natural language. Built with LangGraph's implementation of a ReAct agent, the official Neo4j MCP server, and a custom movie recommendations tool.

## Features

- **Natural Language to Cypher**: Ask questions in plain English and get answers from your Neo4j database
- **ReAct Agent Pattern**: Uses reasoning and acting loops for complex reasoning
- **Schema-Aware**: Automatically retrieves and uses database schema for accurate query generation
- **Ontology-Aware**: A local tool exposes the domain ontology (meanings, aliases, cardinality) alongside the raw schema
- **Interactive CLI**: Chat-based interface for easy interaction

## Prerequisites

- Python 3.11 or higher
- `uv` (required even if you install with pip — it installs the dependencies and runs the
  Neo4j MCP server via `uvx`)
- Neo4j Aura account or local Neo4j instance with Movies database (the demo credentials in
  `.env.example` work out of the box — see [Configuration](#configuration))
- OpenAI API key

## Installation

### Option 1: Using uv (Recommended)

1. **Install uv** (if not already installed):

    [Install Documentation](https://docs.astral.sh/uv/getting-started/installation/)
   ```bash
   pip install uv
   ```

2. **Clone and setup the project**:
   ```bash
   git clone <this-repository-url>
   cd text2cypher-ontology-agent
   ```

3. **Install dependencies**:
   ```bash
   uv sync
   ```

### Option 2: Using pip

1. **Clone and setup the project**:
   ```bash
   git clone <this-repository-url>
   cd text2cypher-ontology-agent
   ```

2. **Create and activate virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Note: `uv` is still required on this path — the agent launches the Neo4j MCP server with
   `uvx` at runtime. If you installed with pip, keep `uv` on your PATH
   (`pip install uv`), or adapt `mcp_server.py` to run the server another way.

## Configuration

1. **Copy the example environment file**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your credentials**:
   ```bash
   OPENAI_API_KEY=your_openai_api_key_here
   NEO4J_USERNAME=neo4j
   NEO4J_PASSWORD=your_neo4j_password
   NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
   NEO4J_DATABASE=neo4j
   ```

## Agent Components

### Core Agent (`single_file_agent.py`)
- **LangGraph ReAct Agent**: Implements reasoning and acting loops for complex queries
- **Neo4j MCP Server** (official): Provides schema introspection and query execution
- **Custom Recommendations Tool**: Custom tool for movie recs
- **Ontology Tool**: Custom tool exposing the domain ontology to the agent
- **Interactive CLI**: Command-line chat interface

### Key Tools Available to the Agent

1. **`get-schema`**: Retrieves database schema for informed query writing
2. **`read-cypher`**: Executes read-only Cypher queries against the database  
3. **`find_movie_recommendations`**: Custom recommendation engine that finds movies liked by users who also enjoyed a target movie
4. **`get_ontology`**: Retrieves the domain ontology — what labels, relationship types and properties *mean* — as a compact schema card (see below)

## Ontology-aware Text2Cypher

### Why add an ontology?

`get-schema` returns the **structure** of the graph, inferred from a data sample: labels,
relationship types, property names and types, and whether a property is indexed. It does not
tell the model what any of it **means**. An ontology does, and that difference shows up directly
in the Cypher the agent writes:

| The model needs to know | `get-schema` | Ontology |
|---|---|---|
| Is `budget` in dollars? Is `imdbRating` 0–10 or 0–100? | ❌ just `INTEGER` / `FLOAT` | ✅ `description` ("Production budget in US dollars", "0.0 to 10.0") |
| The user says "performer" — which label is that? | ❌ no `Performer` label in the data → the query silently matches nothing | ✅ `aliases: [Actor, Performer, Director, Filmmaker]` → `Person` |
| What is a `rating` worth? | ❌ just `FLOAT` | ✅ "Rating from 0.5 to 5.0 in half-star increments" — so "5-star" means `rating = 5.0` |
| What is `timestamp` on a rating? | ❌ just `INTEGER` | ✅ "Unix epoch seconds when the rating was given" |
| Does every movie have a genre? | ❌ | ✅ `IN_GENRE` has `min_count: 1` at the Genre end — so a query can rely on it |
| How is a title with "The" stored? | ❌ | ✅ "`Title, The`" |
| What data exists right now (values, counts)? | ✅ | ❌ |

Concretely, for the question *"Which movies had a production budget of at least 300 million
dollars?"* the schema-only agent sees `budget: INTEGER` and must work out the unit — is the value
in millions or dollars? It either guesses or spends an extra `read-cypher` query sampling values.
The ontology card says "Production budget in US dollars", so the first query is
`WHERE m.budget >= 300000000`. Same for *"Which performers acted in 'The Matrix'?"* — the
ontology resolves "performer" to `Person` and documents the `'Title, The'` convention, so the
query matches `Matrix, The` without a discovery round-trip.

Every claim in this ontology is verified against the actual database: `Actor` and `Director`
exist as secondary labels on `Person`, relationships absent from the data (`REVIEWED`,
`PRODUCED`, `WROTE`, `FOLLOWS`) are deliberately not declared, and each cardinality was checked
with a `NOT EXISTS` query (41 movies have no actor and 55 no director, so `min_count` is 0 for
both; every movie has at least one genre). An ontology that invents structure the data does not
have would mislead the agent — faithfulness is part of what makes it a governed artifact.

The ontology is also a **governed artifact**: it is written down, versionable, reviewable and
validatable against a published JSON Schema, rather than inferred differently on every call.

### How it works

The `get_ontology` tool ([tools/get_ontology.py](tools/get_ontology.py)) exposes a document
written in the [Neo4j Ontology Graph Specification](https://github.com/neo4j/ontology-graph-spec) —
a public YAML/JSON format for describing graph models. The example ontology for the Movies domain
lives in [ontology/movies.ontology.yaml](ontology/movies.ontology.yaml).

The tool returns a compact "schema card" instead of the whole document (about 40 tokens per
entity — roughly 400 for this Movies ontology), and accepts parameters that matter when the
ontology is too large for the model's context:

- **`entities`**: build a sub-schema card from only the entities the question needs (matched against labels, relationship types and their aliases), including the relationships between them. This is the pattern to use for large ontologies: the agent fetches only the relevant slice.
- **`search`**: case-insensitive substring match against labels, relationship types, aliases and descriptions — use it to resolve vocabulary ("performer" finds `Person` via its alias).
- **`include_properties`**: omit property details to get an even smaller card.
- **`source`**: where to read the ontology from:
  - `source="file"` (default) reads a YAML or JSON document from disk, `ONTOLOGY_FILE` in `.env` (defaults to `ontology/movies.ontology.yaml`).
  - `source="db"` reads the ontology persisted in the database itself with `CALL db.ontology.get()`. Ontology persistence in the DBMS is planned for Neo4j 2026.12 (self-managed & Aura); until your database supports it, use `source="file"` — for very large ontologies, store the document as data in a separate database and select sub-schemas with `entities`.

As a safety net for very large ontologies, if a card would exceed ~2,000 tokens the tool
returns an **entity index** instead — one line per entity ("label — one-line description")
plus a note to call again with `entities` for the ones needed (~140 tokens for this ontology).
The "no match" response lists the available entities, capped at 20.

A card looks like this (excerpt):

```markdown
### Person (aliases: Actor, Performer, Director, Filmmaker)
A person in the film industry. The same nodes also carry the secondary labels Actor and Director.
Properties:
- name: STRING (key) - Full name.
- born: INTEGER - Year of birth.

### User -[RATED]-> Movie
A user rated a film.
Cardinality: min 0 at User end, min 0 at Movie end
Properties:
- rating: FLOAT - Rating from 0.5 to 5.0 in half-star increments.
- timestamp: INTEGER - Unix epoch seconds when the rating was given.
```

**How the agent chooses between the two tools:** it is instructed to prefer `get_ontology` for
schema context, and to fall back to `get-schema` only when the ontology has no matching
entity (the tool's response lists what is available), or when the question depends on
data-dependent facts the ontology cannot know — actual values, populated properties, counts.

#### How big is the card?

Approximate sizes for this ontology (4 characters ≈ 1 token):

| Call | Size |
|---|---|
| Full card (13 entities) | ~400 tokens |
| Sub-schema, 3 entities | ~250 tokens |
| Sub-schema, 3 entities, no properties | ~140 tokens |

A few hundred tokens is small enough to fetch without thinking about it. For ontologies with
hundreds of entities, always use `entities` so the card stays in this range regardless of the
ontology's total size.

**Small ontology: preload it or keep it a tool?** For an ontology this small you could paste the
card into the system prompt instead of exposing a tool. Preloading saves one tool round-trip per
question but costs those tokens on *every* call, even for questions that never need schema
context; the tool costs one round-trip but only when schema context is actually needed, and it
scales (via `entities`) to ontologies that would never fit in a prompt. This example keeps it a
tool because that is the pattern that scales; for a small, always-needed ontology, preloading is
a reasonable simplification.

### What we measured

This repo is template code: it shows how to add an ontology to a text2cypher agent, and how to
measure what it changes. On our 16-question benchmark the answers are **roughly the same with and
without the ontology** — a capable model answers most of these questions correctly from the raw
schema. What differs is the path to the answer: on questions where units, aliases or storage
conventions matter, the ontology agent asks fewer follow-up queries because it does not have to
discover those facts by sampling the data. On the six questions written to probe exactly that,
the ontology run used about 2 tool calls per question versus about 3 without it, and roughly
half the time per question (small sample, and absolute
latency varies with API load — directional, not a benchmark claim). RAGAS factual
correctness was too noisy on list-style answers to lead with, so we don't.

If your domain has many entities, ambiguous property names, or vocabulary your users do not share
with the database, an ontology is worth trying. If your schema is small and self-explanatory, the
raw schema may be all you need — this example gives you both configurations so you can measure it
on your own questions.

### Pros and cons

Not every benefit below is measured by the eval in this repo — this is template code, so treat them
as things to evaluate for your own domain.

**Pros**

- **The agent knows what things mean.** Units, scales and formats are written down ("budget in US
  dollars", "imdbRating 0–10", titles stored as `Title, The`), so it guesses less and needs fewer
  exploratory queries.
- **Your users' words map to your data.** Aliases resolve "performer" or "filmmaker" to `Person`.
- **A written, reviewed artifact.** It lives in version control, is validated against the published
  JSON Schema, and returns the same answer every run — unlike a schema inferred from a data sample.
- **Works on an empty or sparse database.** The model is declared, not observed, so it is there on
  day one and for properties or relationships a sample would miss.
- **Scales to large graphs.** The `entities` parameter fetches only the part of the ontology a
  question needs, keeping the context small when the full model is big.
- **Can act as a guardrail.** Allowed values, patterns and cardinality can be used to check
  generated queries before they run (`rating` can't exceed 5.0, only declared properties exist).
- **Shared by other tools.** One file can serve several agents, BI tools and documentation, so they
  cannot drift apart.

**Cons**

- **Someone has to maintain it.** The ontology must stay faithful to the data. One that invents
  relationships or wrong cardinalities actively misleads the agent — we hit exactly this with our
  first draft and had to correct it against the database.
- **It is another thing to govern.** Changes need review, and schema changes have to be reflected
  in two places (the database and the ontology).
- **It may not pay off.** For small, self-explanatory schemas the raw schema is enough; in our
  measurements the answers were about the same with and without it.
- **The tooling is early.** The specification is new (1.1.0), and reading the ontology from the
  database (`source="db"`) is not available yet — today it is a file you point the agent at.

To adapt this to your own domain, write your ontology in the [specification format](https://github.com/neo4j/ontology-graph-spec) (validate it against the published JSON Schema), point `ONTOLOGY_FILE` at it, and the agent picks it up — no other code changes needed.

The evaluation suite makes it easy to measure the difference: run it once with `WITH_ONTOLOGY=true` (default) and once with `WITH_ONTOLOGY=false`, then compare the results. Results land in `evals/output/eval_run_<timestamp>_<ontology|no_ontology>/`.

## Running the Agent

### Using uv (Recommended)
```bash
make run-agent-uv
# or
uv run python3 single_file_agent.py
```

### Using pip/standard Python
```bash
make run-agent
# or
python3 single_file_agent.py
```

## Usage Examples

Once running, you can ask questions like:
- "What movies are in the database?"
- "Tell me about The Matrix"
- "Recommend me some films like The Dark Knight."

## Exit Commands
To exit the agent, type any of:
- `exit`
- `quit` 
- `q`

## Evaluation

This repo contains a comprehensive local evaluation suite with [RAGAS](https://docs.ragas.io/) metrics for measuring agent performance. The evaluation system can be used and extended to evaluate your own agents.

### Evaluation Metrics

The evaluation suite includes three RAGAS metrics:

1. **[Rouge Score](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/traditional/#rouge-score)** - Measures the longest common subsequence between the reference answer and agent response using F1 score
2. **[Factual Correctness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/#factual-correctness)** - Uses an LLM judge to evaluate the factual accuracy of the agent's response against the reference answer with high atomicity and coverage
3. **[Answer Relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/#answer-relevancy)** - Measures how relevant the agent's response is to the user's question using embeddings

### Running Evaluations

1. Populate the `questions.yaml` file with your eval question set
2. Configure the model and the tools in [evaluation/main.py](evaluation/main.py) if needed
   (`OPENAI_MODEL`, `JUDGE_MODEL` and `WITH_ONTOLOGY` are read from `.env`)
3. Run evaluations:
   ```bash
   make run-eval-uv  # Using uv
   # or
   make run-eval     # Using pip
   ```
4. The results are written to `evals/output/eval_run_<timestamp>_<ontology|no_ontology>/`:
   `metadata.csv`, `agent_response.csv`, `failed_response.csv` and a `report.txt`
5. View and analyze the results with [review.ipynb](review.ipynb)

**NOTE**: The evaluation script may take awhile to run depending on the number of questions and length of resulting conversations

### Eval CSV Structure

The resulting evaluation CSV contains the following columns:

**Question & Answer Data:**
* `question_id`: str - Unique identifier for the question
* `question`: str - The user's input question
* `expected_answer`: str - Reference answer for comparison
* `agent_final_answer`: Optional[str] - The agent's response

**Agent Performance Metrics:**
* `generated_cypher`: list[ReadNeo4jCypherToolInput] - All Cypher queries generated
* `model`: str - LLM model used
* `available_tools`: list[str] - Tools available to the agent
* `called_tools`: list[str] - Tools actually invoked
* `num_messages`: Optional[int] - Total messages in conversation
* `num_llm_calls`: Optional[int] - Number of LLM invocations
* `num_tool_calls`: Optional[int] - Number of tool invocations
* `response_time`: Optional[float] - Time to complete question (seconds)
* `error`: Optional[str] - Error message if evaluation failed

**RAGAS Quality Metrics:**
* `rouge_f1_score`: Optional[float] - Rouge-L F1 score
* `factual_correctness_f1_score`: Optional[float] - Factual correctness F1 score
* `answer_relevancy_score`: Optional[float] - Answer relevancy score

## Development

### Code Formatting
```bash
make format
```



## Dependencies

**Core Libraries:**
- `langchain` - LangChain framework
- `langchain-mcp-adapters` - MCP (Model Context Protocol) adapters
- `langchain-openai` - OpenAI integration
- `langgraph` - Graph-based agent framework
- `neo4j` - Neo4j Python driver
- `openai` - OpenAI API client
- `pydantic` - Data validation

**Evaluation Libraries:**
- `ragas` - RAG & agent assessment metrics framework
- `rouge-score` - Text similarity metrics
- `pandas` - Data analysis and CSV handling

**Development:**
- `ruff` - Code formatting and linting

## Troubleshooting

**Connection Issues:**
- Verify your Neo4j credentials in `.env`
- Ensure your Neo4j instance is running and accessible

**OpenAI Issues:**
- Verify your OpenAI API key is valid
- Check your API usage limits

**MCP Server Issues:**
- Ensure `uvx` is available in your PATH
- The agent automatically installs the official `neo4j-mcp-server@2.1.1` via uvx

**Python Issues:**
- Ensure Python 3.11+ is installed
- Try recreating your virtual environment if using pip

## Credits

This repository is a fork of
[neo4j-field/text2cypher-react-agent-example](https://github.com/neo4j-field/text2cypher-react-agent-example)
by the Neo4j Field team — the agent skeleton, the evaluation harness and the recommendation
tool come from there. The ontology tool, the ontology-aware prompt and the A/B evaluation
setup were added in this fork.

## License

This project is provided as an example for educational and demonstration purposes.
