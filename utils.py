import yaml
from langchain.agents.middleware import ModelRequest, wrap_model_call
from langchain_core.messages import AnyMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages


def get_questions_from_yaml(file_path: str) -> list[dict[str, str]]:
    """
    Get the questions from the yaml file.

    Parameters
    ----------
    file_path: str
        The path to the yaml file.

    Returns
    -------
    list[dict[str, str]]
        A list of dictionaries with the following keys:
        - question: str -> The question to answer.
        - answer: str -> The expected answer to the question.
        - id: str -> The id of the question.
    """
    with open(file_path, "r") as file:
        return yaml.safe_load(file).get("questions", [])


def message_text(message: AnyMessage) -> str:
    """
    Return the text of a message as a plain string.

    With the OpenAI Responses API, `AIMessage.content` is a list of content
    blocks (e.g. `[{"type": "text", "text": "42"}]`) rather than a string.
    Flatten the text blocks so the result can be written to CSV or scored.

    Parameters
    ----------
    message : AnyMessage
        The message to extract text from.

    Returns
    -------
    str
        The message text.
    """

    content = message.content
    if isinstance(content, str):
        return content

    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(part for part in parts if part)


@wrap_model_call
async def trim_history(request: ModelRequest, handler):
    """
    Middleware that keeps the model context under the token budget.

    Called before every model call. It trims the conversation history that is
    sent to the LLM without modifying the messages stored in the graph state.

    Documentation:
    https://docs.langchain.com/oss/python/langchain/middleware

    Parameters
    ----------
    request : ModelRequest
        The model request (its `messages` exclude the system prompt).
    handler : callable
        The function that calls the model with the (possibly modified) request.

    Returns
    -------
    ModelResponse
        The model response.
    """

    trimmed_messages = trim_messages(
        request.messages,
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=30_000,
        start_on="human",
        end_on=("human", "tool"),
    )
    return await handler(request.override(messages=trimmed_messages))


async def print_astream(async_stream) -> None:
    """
    Print the stream of messages from the agent.

    Parameters
    ----------
    async_stream : AsyncGenerator[dict[str, dict[str, list[AnyMessage]]], None]
        The stream of messages from the agent.
    """

    async for chunk in async_stream:
        for node, update in chunk.items():
            print(f"Update from node: {node}")
            for message in update.get("messages", []):
                if isinstance(message, tuple):
                    print(message)
                else:
                    message.pretty_print()

        print("\n\n")
