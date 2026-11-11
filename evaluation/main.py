"""Evaluation harness: runs the agent over questions.yaml and scores the answers.

The agent under test is built with `build_tools`/`build_agent` from
single_file_agent.py, so the evaluation measures exactly the agent customers
run. Results land in evals/output/eval_run_<timestamp>_<ontology|no_ontology>/
as metadata.csv, agent_response.csv, failed_response.csv and report.txt.
"""

import asyncio
import os
from datetime import datetime
from time import perf_counter
from typing import Optional
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
from langgraph.graph.state import CompiledStateGraph
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from evaluation.components.agent import build_scorers, create_agent_response_record
from evaluation.components.generate_report import create_report_from_dataframes
from evaluation.components.metadata import create_metadata_record
from evaluation.models import (
    AgentResponseTableRecord,
    FailedResponseTableRecord,
    MetadataTableRecord,
    QuestionRecord,
)
from llm import get_agent_model
from mcp_server import get_neo4j_mcp_server
from prompt import ontology_enabled
from single_file_agent import build_agent, build_tools
from utils import get_questions_from_yaml, message_text

if load_dotenv():
    print("Loaded .env file")
else:
    print("No .env file found")

EVALS_LOC = "evals/output/"
# How many questions run against the model at the same time.
MAX_CONCURRENT_QUESTIONS = 20


async def evaluate_single_question(
    agent: CompiledStateGraph,
    question_dict: dict[str, str],
    tool_names: list[str],
    model: str,
    scorers,
) -> tuple[
    Optional[MetadataTableRecord],
    Optional[AgentResponseTableRecord],
    Optional[FailedResponseTableRecord],
]:
    """
    Run one question against the agent in its own conversation thread, and
    score the answer. Returns the records that could be created; the others
    are None (a failed record replaces the other two on error).
    """

    try:
        if question_dict.get("question") is None:
            raise ValueError("Question not found")

        # Each question gets its own thread id so conversations stay independent.
        thread_id = "eval-" + question_dict.get("id", str(uuid4()))
        config = {"configurable": {"thread_id": thread_id}}

        response_time_start = perf_counter()
        response = await agent.ainvoke({"messages": question_dict["question"]}, config=config)
        response_time = perf_counter() - response_time_start

        metadata_record = create_metadata_record(
            question_id=question_dict.get("id"),
            question=question_dict.get("question"),
            expected_answer=question_dict.get("answer"),
            agent_response=response,
            model=model,
            available_tools=tool_names,
            response_time=response_time,
        )

        agent_response_record = await create_agent_response_record(
            scorers,
            question_id=question_dict.get("id"),
            question=question_dict.get("question"),
            expected_answer=question_dict.get("answer"),
            agent_final_answer=message_text(response["messages"][-1]),
            model=model,
        )

        print(f"Completed evaluation for question: {question_dict.get('question')}")

        return metadata_record, agent_response_record, None

    except Exception as e:
        print(f"Error: {e}")
        failed_record = FailedResponseTableRecord(
            question_id=question_dict.get("id"),
            question=question_dict.get("question"),
            expected_answer=question_dict.get("answer"),
            error=str(e),
        )
        return None, None, failed_record


async def evaluate_questions(
    agent: CompiledStateGraph,
    questions: list[QuestionRecord],
    tool_names: list[str],
    model: str,
    scorers,
    max_concurrent: int = MAX_CONCURRENT_QUESTIONS,
) -> list[
    tuple[
        Optional[MetadataTableRecord],
        Optional[AgentResponseTableRecord],
        Optional[FailedResponseTableRecord],
    ]
]:
    """
    Evaluate all questions, at most `max_concurrent` at a time.

    Returns
    -------
    list
        One (metadata, agent_response, failed) tuple per question, in order.
    """

    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_one(question_dict: dict[str, str]):
        async with semaphore:
            return await evaluate_single_question(agent, question_dict, tool_names, model, scorers)

    return await asyncio.gather(*(run_one(question_dict) for question_dict in questions))


async def main():
    """
    Main function to run the agent evaluation.

    Based on the documentation:
    https://github.com/langchain-ai/langchain-mcp-adapters?tab=readme-ov-file#client
    """

    questions = get_questions_from_yaml("questions.yaml")
    print(f"Retrieved {len(questions)} questions for evaluation.")

    scorers = build_scorers()
    model = get_agent_model()

    metadata_records = list()
    agent_response_records = list()
    failed_response_records = list()

    async with stdio_client(get_neo4j_mcp_server()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await build_tools(session)
            agent = build_agent(tools)

            results = await evaluate_questions(
                agent, questions, [tool.name for tool in tools], model, scorers
            )

    for metadata_record, agent_response_record, failed_record in results:
        if metadata_record is not None:
            metadata_records.append(metadata_record)
        if agent_response_record is not None:
            agent_response_records.append(agent_response_record)
        if failed_record is not None:
            failed_response_records.append(failed_record)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    condition = "ontology" if ontology_enabled() else "no_ontology"
    directory = f"{EVALS_LOC}eval_run_{timestamp}_{condition}"

    os.makedirs(directory, exist_ok=True)

    metadata_df = pd.DataFrame(metadata_records)
    agent_response_df = pd.DataFrame(agent_response_records)

    metadata_df.to_csv(
        f"{directory}/metadata.csv",
        index=False,
    )

    agent_response_df.to_csv(
        f"{directory}/agent_response.csv",
        index=False,
    )

    failed_response_df = pd.DataFrame(
        failed_response_records,
        columns=list(FailedResponseTableRecord.__annotations__.keys()),
    )
    failed_response_df.to_csv(
        f"{directory}/failed_response.csv",
        index=False,
    )

    report = create_report_from_dataframes(
        title=f"Evaluation Report {timestamp}",
        agent_response_df=agent_response_df,
        metadata_df=metadata_df,
        failed_response_df=failed_response_df,
    )

    with open(f"{directory}/report.txt", "w") as f:
        f.write(report)


if __name__ == "__main__":
    asyncio.run(main())
