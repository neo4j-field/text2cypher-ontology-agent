"""Metadata extraction from an agent response."""

from typing import Any, Optional

from langchain_core.messages import AIMessage

from evaluation.models import MetadataTableRecord
from utils import message_text


def create_metadata_record(
    question_id: str,
    question: str,
    expected_answer: str,
    agent_response: dict[str, Any],
    model: str,
    available_tools: list[str],
    response_time: Optional[float],
) -> MetadataTableRecord:
    """
    Create a metadata record describing how the agent answered one question:
    which tools it called, which Cypher queries it generated and how long it
    took. If extraction fails, a sparse record with the error is returned.
    """

    try:
        # Every AIMessage may carry tool calls; collect them all.
        tool_calls = [
            tool_call
            for message in agent_response["messages"]
            if isinstance(message, AIMessage)
            for tool_call in message.tool_calls
        ]

        # capture all text2cypher queries
        cyphers = [c.get("args") for c in tool_calls if c.get("name") == "read-cypher"]

        return MetadataTableRecord(
            question_id=question_id,
            question=question,
            expected_answer=expected_answer,
            agent_final_answer=message_text(agent_response["messages"][-1]),
            generated_cypher=cyphers,
            model=model,
            available_tools=available_tools,
            called_tools=tool_calls,
            num_messages=len(agent_response["messages"]),
            num_llm_calls=len([m for m in agent_response["messages"] if isinstance(m, AIMessage)]),
            num_tool_calls=len(tool_calls),
            response_time=response_time,
            error=None,
        )
    except Exception as e:
        return MetadataTableRecord(
            question_id=question_id,
            question=question,
            expected_answer=expected_answer,
            agent_final_answer=None,
            generated_cypher=[],
            model=model,
            available_tools=available_tools,
            called_tools=[],
            num_messages=None,
            num_llm_calls=None,
            num_tool_calls=None,
            response_time=response_time,
            error=str(e),
        )
