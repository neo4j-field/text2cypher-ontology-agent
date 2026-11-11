# The Ontology Tool

This document explains what the ontology adds to a text2cypher agent, how the
`get_ontology` tool works, what it costs, and how to adapt it to your own domain.
For how to measure the difference on your own questions, see [evaluation.md](evaluation.md).

## Why add an ontology?

`get-schema` (the official Neo4j MCP server's schema tool) returns the **structure** of the
graph, inferred from a data sample: labels, relationship types, property names and types, and
whether a property is indexed. It does not tell the model what any of it **means**. An
ontology does, and that difference shows up directly in the Cypher the agent writes:

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
dollars?"* the schema-only agent sees `budget: INTEGER` and must work out the unit — is the
value in millions or dollars? It either guesses or spends an extra `read-cypher` query sampling
values. The ontology card says "Production budget in US dollars", so the first query is
`WHERE m.budget >= 300000000`. Same for *"Which performers acted in 'The Matrix'?"* — the
ontology resolves "performer" to `Person` and documents the `'Title, The'` convention, so the
query matches `Matrix, The` without a discovery round-trip.

## Faithfulness matters

Every claim in this ontology is verified against the actual database: `Actor` and `Director`
exist as secondary labels on `Person`, relationships absent from the data (`REVIEWED`,
`PRODUCED`, `WROTE`, `FOLLOWS`) are deliberately not declared, and each cardinality was checked
with a `NOT EXISTS` query (41 movies have no actor and 55 no director, so `min_count` is 0 for
both; every movie has at least one genre).

An ontology that invents structure the data does not have actively misleads the agent — we hit
exactly this with our first draft and had to correct it against the database. When you write
your own, verify claims against the data before trusting the agent with them.

The flip side of that discipline: the ontology is a **governed artifact** — written down,
versionable, reviewable and validatable against a published JSON Schema, rather than inferred
differently on every call.

## How the tool works

The `get_ontology` tool ([tools/get_ontology.py](../tools/get_ontology.py)) exposes a document
written in the [Neo4j Ontology Graph Specification](https://github.com/neo4j/ontology-graph-spec) —
a public YAML/JSON format for describing graph models. The example ontology for the Movies
domain lives in [ontology/movies.ontology.yaml](../ontology/movies.ontology.yaml).

The tool returns a compact "schema card" instead of the whole document (about 50 tokens per
entity — roughly 400 for this 8-entity Movies ontology), and accepts parameters that matter
when the ontology is too large for the model's context:

- **`entities`**: build a sub-schema card from only the entities the question needs (matched
  against labels, relationship types and their aliases), including the relationships between
  them. This is the pattern to use for large ontologies: the agent fetches only the relevant
  slice.
- **`search`**: case-insensitive substring match against labels, relationship types, aliases
  and descriptions — use it to resolve vocabulary ("performer" finds `Person` via its alias).
- **`include_properties`**: omit property details to get an even smaller card.

Where the ontology is read from is a deployment choice, not something the model decides:
`ONTOLOGY_SOURCE=file` (default) reads a YAML or JSON document from disk (`ONTOLOGY_FILE` in
`.env`, defaults to `ontology/movies.ontology.yaml`); `ONTOLOGY_SOURCE=db` reads the ontology
persisted in the database itself with `CALL db.ontology.get()` — ontology persistence in the
DBMS is planned for a future Neo4j release (2026.12 target, timing TBC). Until your database
supports it, use the file source; for very large ontologies, store the document as data in a
separate database and select sub-schemas with `entities`.

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

**How the agent chooses between the two schema tools:** it is instructed to prefer
`get_ontology` for schema context, and to fall back to `get-schema` only when the ontology has
no matching entity (the tool's response lists what is available), or when the question depends
on data-dependent facts the ontology cannot know — actual values, populated properties, counts.

## How big is the card?

Approximate sizes for this ontology (4 characters ≈ 1 token):

| Call | Size |
|---|---|
| Full card (8 entities) | ~400 tokens |
| Sub-schema, 3 entities | ~250 tokens |
| Sub-schema, 3 entities, no properties | ~140 tokens |

A few hundred tokens is small enough to fetch without thinking about it. For ontologies with
hundreds of entities, always use `entities` so the card stays in this range regardless of the
ontology's total size.

**Small ontology: preload it or keep it a tool?** For an ontology this small you could paste
the card into the system prompt instead of exposing a tool. Preloading saves one tool
round-trip per question but costs those tokens on *every* call, even for questions that never
need schema context; the tool costs one round-trip but only when schema context is actually
needed, and it scales (via `entities`) to ontologies that would never fit in a prompt. This
example keeps it a tool because that is the pattern that scales; for a small, always-needed
ontology, preloading is a reasonable simplification.

## Pros and cons

Not every benefit below is measured by the eval in this repo — this is template code, so treat
them as things to evaluate for your own domain.

**Pros**

- **The agent knows what things mean.** Units, scales and formats are written down ("budget
  in US dollars", "imdbRating 0–10", titles stored as `Title, The`), so it guesses less and
  needs fewer exploratory queries.
- **Your users' words map to your data.** Aliases resolve "performer" or "filmmaker" to `Person`.
- **A written, reviewed artifact.** It lives in version control, is validated against the
  published JSON Schema, and returns the same answer every run — unlike a schema inferred
  from a data sample.
- **Works on an empty or sparse database.** The model is declared, not observed, so it is
  there on day one and for properties or relationships a sample would miss.
- **Scales to large graphs.** The `entities` parameter fetches only the part of the ontology a
  question needs, keeping the context small when the full model is big.
- **Can act as a guardrail.** Allowed values, patterns and cardinality can be used to check
  generated queries before they run (`rating` can't exceed 5.0, only declared properties exist).
- **Shared by other tools.** One file can serve several agents, BI tools and documentation, so
  they cannot drift apart.

**Cons**

- **Someone has to maintain it.** The ontology must stay faithful to the data (see
  [Faithfulness matters](#faithfulness-matters) above).
- **It is another thing to govern.** Changes need review, and schema changes have to be
  reflected in two places (the database and the ontology).
- **It may not pay off.** For small, self-explanatory schemas the raw schema is enough; in our
  measurements the answers were about the same with and without it (see
  [evaluation.md](evaluation.md)).
- **The tooling is early.** The specification is new (1.1.0), and reading the ontology from
  the database (`ONTOLOGY_SOURCE=db`) is not available yet — today it is a file you point the
  agent at.

## Adapting to your own domain

The template is Movies-specific in four places. To adapt it:

1. **The ontology** — write your own in the
   [specification format](https://github.com/neo4j/ontology-graph-spec) and validate it
   against the published JSON Schema (`uv run python tests/smoke_test.py` shows how, and
   validates `ontology/movies.ontology.yaml` against it). Point `ONTOLOGY_FILE` at it;
   no other code changes are needed for the ontology itself.
2. **The system prompt** — [prompt.py](../prompt.py) is written for movie questions; rewrite
   the domain-specific parts for your data.
3. **The custom tool** — `find_movie_recommendations` in
   [single_file_agent.py](../single_file_agent.py) is a Movies demo; replace it with tools for
   your domain, or remove it.
4. **The eval questions** — write your own questions and reference answers in
   [questions.yaml](../questions.yaml), then run both conditions to measure what the ontology
   changes on *your* questions (see [evaluation.md](evaluation.md)).
