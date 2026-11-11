"""RAGAS scorers used to evaluate the agent's answers."""

from openai import AsyncOpenAI
from ragas.embeddings.base import embedding_factory
from ragas.llms import llm_factory
from ragas.metrics.collections import AnswerRelevancy, FactualCorrectness, RougeScore

from evaluation.models import AgentResponseTableRecord
from llm import get_judge_model


def build_scorers() -> tuple[RougeScore, FactualCorrectness, AnswerRelevancy]:
    """
    Create the three RAGAS scorers, sharing one judge LLM and embeddings client.

    The judge model (JUDGE_MODEL in .env) is one tier above the agent to limit
    self-preference in the scores. RAGAS's structured-output path uses Chat
    Completions function tools, which GPT-6 models only support with reasoning
    disabled, hence `reasoning_effort="none"`.

    Returns
    -------
    tuple[RougeScore, FactualCorrectness, AnswerRelevancy]
        The ROUGE-L, factual correctness and answer relevancy scorers.
    """

    client = AsyncOpenAI()
    # max_tokens matters: the default (1024) truncates the judge's claim
    # decomposition on long, list-style answers, which fails the whole
    # FactualCorrectness score for that question.
    judge = llm_factory(get_judge_model(), client=client, reasoning_effort="none", max_tokens=8192)
    embeddings = embedding_factory(
        "openai",
        model="text-embedding-3-small",
        client=client,
        interface="modern",
    )

    # https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/traditional/#rouge-score
    # looks at the longest common subsequence between the reference and the response
    rouge_scorer = RougeScore(rouge_type="rougeL", mode="fmeasure")

    # https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/
    # an LLM judge evaluates the factual accuracy of the response against the reference
    factual_correctness_scorer = FactualCorrectness(
        llm=judge, mode="f1", atomicity="high", coverage="high"
    )

    # https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/
    # measures how relevant the response is to the question, using embeddings
    answer_relevancy_scorer = AnswerRelevancy(llm=judge, embeddings=embeddings)

    return rouge_scorer, factual_correctness_scorer, answer_relevancy_scorer


async def create_agent_response_record(
    scorers: tuple[RougeScore, FactualCorrectness, AnswerRelevancy],
    question_id: str,
    question: str,
    expected_answer: str,
    agent_final_answer: str,
    model: str,
) -> AgentResponseTableRecord:
    """
    Score one agent answer with the three RAGAS metrics.

    Parameters
    ----------
    scorers : tuple[RougeScore, FactualCorrectness, AnswerRelevancy]
        The scorers from `build_scorers`, reused across questions.
    question_id : str
        The question's unique identifier.
    question : str
        The user's question.
    expected_answer : str
        The reference answer to score against.
    agent_final_answer : str
        The agent's response to score.
    model : str
        The model that produced the response.

    Returns
    -------
    AgentResponseTableRecord
        The scored answer, or a record with the error if scoring failed.
    """

    rouge_scorer, factual_correctness_scorer, answer_relevancy_scorer = scorers

    try:
        rouge_score = await rouge_scorer.ascore(
            reference=expected_answer, response=agent_final_answer
        )
        factual_correctness_score = await factual_correctness_scorer.ascore(
            response=agent_final_answer, reference=expected_answer
        )
        answer_relevancy_score = await answer_relevancy_scorer.ascore(
            user_input=question, response=agent_final_answer
        )

        return AgentResponseTableRecord(
            question_id=question_id,
            question=question,
            expected_answer=expected_answer,
            agent_final_answer=agent_final_answer,
            model=model,
            rouge_f1_score=rouge_score.value,
            factual_correctness_f1_score=factual_correctness_score.value,
            answer_relevancy_score=answer_relevancy_score.value,
            error=None,
        )
    except Exception as e:
        return AgentResponseTableRecord(
            question_id=question_id,
            question=question,
            expected_answer=expected_answer,
            agent_final_answer=None,
            model=model,
            rouge_f1_score=None,
            factual_correctness_f1_score=None,
            answer_relevancy_score=None,
            error=str(e),
        )
