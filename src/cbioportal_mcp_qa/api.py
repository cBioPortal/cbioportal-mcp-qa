"""FastAPI wrapper exposing the ask command with an OpenAI-compatible interface."""

from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse, StreamingResponse

from .openai_adapter import chat_completion_response, sse_chat_completions

from .llm_client import DEFAULT_MODEL, LLMClient
from .sql_logger import sql_query_logger

DEFAULT_CHUNK_SIZE = 1200

app = FastAPI()


class Message(BaseModel):
    role: str = Field(..., description="Role of the message sender (e.g., user).")
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messages: List[Message]
    stream: bool = True
    include_sql: bool = True


def _extract_user_question(messages: List[Message]) -> Optional[str]:
    """Return the most recent user message content."""
    for message in reversed(messages):
        if message.role.lower() == "user":
            return message.content
    return None


def _chunk_answer(answer: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[str]:
    """Split the answer into smaller pieces to feed the SSE adapter."""
    if not answer:
        return [""]
    return [answer[i : i + chunk_size] for i in range(0, len(answer), chunk_size)]


@app.post("/chat/completions")
async def chat_completions(chat_request: ChatCompletionRequest):
    print("-- -- [api] incoming request", chat_request.model_dump(exclude_none=True))
    if getattr(chat_request, "model_extra", None):
        print("-- -- [api] extra params ignored", chat_request.model_extra)

    question = _extract_user_question(chat_request.messages)
    if not question:
        raise HTTPException(
            status_code=400, detail="A user message is required to ask a question."
        )

    try:
        llm_client = LLMClient(
            model=DEFAULT_MODEL,
            include_sql=chat_request.include_sql,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    answer = await llm_client.ask_question(question)

    if chat_request.include_sql:
        sql_markdown = sql_query_logger.get_queries_markdown()
        if sql_markdown:
            answer = f"{answer}\n\n---\n{sql_markdown}"

    chunks = _chunk_answer(answer)

    if chat_request.stream:
        print(
            "-- -- [api] streaming response body",
            {"model_used": DEFAULT_MODEL, "chunk_count": len(chunks), "chunks": chunks},
        )
        return StreamingResponse(
            sse_chat_completions(chunks, model=DEFAULT_MODEL),
            media_type="text/event-stream",
        )

    payload = chat_completion_response(
        chunk_iterable=chunks,
        model=DEFAULT_MODEL,
        prompt_messages=[message.content for message in chat_request.messages],
    )
    print(
        "-- -- [api] json response body",
        {"model_used": DEFAULT_MODEL, "payload": payload},
    )
    return JSONResponse(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("cbioportal_mcp_qa.api:app", host="0.0.0.0", port=4000, reload=False)
