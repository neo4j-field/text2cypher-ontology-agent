"""Model configuration for the agent and the evaluation judges."""

import os

from langchain_openai import ChatOpenAI

# GPT-6 Luna is OpenAI's cost-efficient tier. It is a good fit for text2cypher:
# the task is text + tool calling + Cypher, not vision or computer use.
DEFAULT_AGENT_MODEL = "gpt-6-luna"

# Judge one tier above the agent to limit self-preference in the RAGAS scores.
# Ragas 0.3.9 cannot parse decimal model versions (e.g. "gpt-6.1-terra") when
# mapping max_tokens -> max_completion_tokens, so use an integer-versioned model.
# Revisit once ragas is upgraded (see the migration todo in CLAUDE.md).
DEFAULT_JUDGE_MODEL = "gpt-6-sol"

DEFAULT_REASONING_EFFORT = "medium"


def get_agent_model() -> str:
    """
    Get the model id used by the agents and the evaluation runs.

    Returns
    -------
    str
        The model id, from `OPENAI_MODEL` or the default.
    """

    return os.getenv("OPENAI_MODEL", DEFAULT_AGENT_MODEL)


def get_judge_model() -> str:
    """
    Get the model id used by the RAGAS judge.

    Returns
    -------
    str
        The model id, from `JUDGE_MODEL` or the default.
    """

    return os.getenv("JUDGE_MODEL", DEFAULT_JUDGE_MODEL)


def build_agent_model() -> ChatOpenAI:
    """
    Create the chat model used by the agent.

    All current OpenAI models expose tool calling through the Responses API
    (GPT-6.1 Terra requires it; GPT-6 Luna supports functions on Chat
    Completions only when reasoning effort is "none"). We always use it.

    Returns
    -------
    ChatOpenAI
        The configured chat model.
    """

    return ChatOpenAI(
        model=get_agent_model(),
        use_responses_api=True,
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
    )
