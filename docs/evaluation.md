# Evaluation

This repo contains a local evaluation suite with [RAGAS](https://docs.ragas.io/) metrics for
measuring agent performance. It exists to answer one question: **what does the ontology change?**
It can also be extended to evaluate your own agents.

## What we measured

This repo is template code: it shows how to add an ontology to a text2cypher agent, and how to
measure what it changes. On our 16-question benchmark the answers are **roughly the same with
and without the ontology** — a capable model answers most of these questions correctly from
the raw schema. What differs is the path to the answer: on questions where units, aliases or
storage conventions matter, the ontology agent asks fewer follow-up queries because it does
not have to discover those facts by sampling the data.

On the six questions written to probe exactly that (budget units, half-star ratings, the
`Title, The` convention, alias vocabulary), across repeated A/B runs:

| | With ontology | Without ontology |
|---|---|---|
| Tool calls per question | ~2 | ~3 |
| LLM calls per question | ~3 | ~3.5 |
| Time per question | roughly half | baseline |

Small sample, and absolute latency varies with API load — directional, not a benchmark claim.
RAGAS factual correctness was too noisy on list-style answers to lead with, so we don't (see
the metric caveats below).

If your domain has many entities, ambiguous property names, or vocabulary your users do not
share with the database, an ontology is worth trying. If your schema is small and
self-explanatory, the raw schema may be all you need — this example gives you both
configurations so you can measure it on your own questions.

## Metrics

The suite scores each answer with three RAGAS metrics (the judge model is `JUDGE_MODEL` in
`.env`, one tier above the agent to limit self-preference):

1. **[Rouge Score](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/traditional/#rouge-score)** —
   longest common subsequence between the reference answer and the agent response (F1).
   Deterministic; strict about wording.
2. **[Factual Correctness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/)** —
   an LLM judge decomposes both answers into atomic claims and checks each response claim
   against the reference. **Caveat:** claims are checked in isolation against the reference
   text, so a correct paraphrase that names its subject ("The Matrix" vs "the movie") can score
   0.0. Useful for spotting real errors, too noisy to compare conditions with — treat
   differences of less than ~0.1 as noise.
3. **[Answer Relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/)** —
   how relevant the response is to the question, using embeddings.

The **effort metrics** in `metadata.csv` (`num_tool_calls`, `num_llm_calls`, `response_time`)
are deterministic and often the more informative comparison — they show *how* the agent
answered, not just whether the final text matches.

## Running evaluations

1. Populate [questions.yaml](../questions.yaml) with your eval question set
   (question, reference answer, optional id)
2. Configure via `.env` as needed: `OPENAI_MODEL`, `JUDGE_MODEL`, `WITH_ONTOLOGY`
3. Run the evaluation:
   ```bash
   make run-eval-uv  # Using uv
   # or
   make run-eval     # Using pip
   ```
4. To measure the ontology's effect, run it twice — once with `WITH_ONTOLOGY=true` (default)
   and once with `WITH_ONTOLOGY=false` — and compare the two run directories.
5. View and analyze the results with [review.ipynb](../review.ipynb)
6. To regenerate `report.txt` for an existing run:
   ```bash
   make generate-report-uv  # most recent run
   make generate-report-uv run=eval_run_2026-11-11_16-09-01_ontology  # a specific run
   ```

**NOTE:** the evaluation may take a while depending on the number of questions and the length
of the resulting conversations. Questions run concurrently (up to 20 at a time), then each
answer is scored by the judge.

## Output layout

Each run writes to `evals/output/eval_run_<timestamp>_<ontology|no_ontology>/`:

**`metadata.csv`** — how the agent answered each question:

* `question_id`, `question`, `expected_answer`, `agent_final_answer`
* `generated_cypher`: the Cypher queries generated
* `model`: the LLM model used
* `available_tools`: the tool names available to the agent
* `called_tools`: the tool calls actually invoked (name + args)
* `num_messages`, `num_llm_calls`, `num_tool_calls`: conversation statistics
* `response_time`: seconds to complete the question
* `error`: error message if the run failed

**`agent_response.csv`** — the quality of each answer (RAGAS metrics):

* `question_id`, `question`, `expected_answer`, `agent_final_answer`, `model`
* `rouge_f1_score`: Rouge-L F1 score
* `factual_correctness_f1_score`: Factual correctness F1 score
* `answer_relevancy_score`: Answer relevancy score
* `error`: error message if scoring failed

**`failed_response.csv`** — questions that crashed the evaluation harness:

* `question_id`, `question`, `expected_answer`, `error`

Plus a human-readable `report.txt` with one section per question.
