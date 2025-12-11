"""
Helpers to format chat responses in OpenAI-compatible shapes (streaming and non-streaming).
"""
import json
import time
import uuid
from typing import AsyncGenerator, Iterable, List, Optional


def _default_ids(created: Optional[int] = None, completion_id: Optional[str] = None):
    created_ts = created or int(time.time())
    cid = completion_id or f"chatcmpl-{uuid.uuid4()}"
    return created_ts, cid


async def sse_chat_completions(
    chunk_iterable: Iterable[str],
    model: str,
    created: Optional[int] = None,
    completion_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Wrap a string chunk iterable into OpenAI-style SSE ChatCompletions chunks.
    Yields already-serialized `data: ...\\n\\n` frames and ends with [DONE].
    """
    created_ts, cid = _default_ids(created, completion_id)
    for chunk in chunk_iterable:
        frame = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": chunk,
                    },
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(frame)}\n\n"
        await _small_sleep()

    final_frame = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_frame)}\n\n"
    yield "data: [DONE]\n\n"


async def _small_sleep():
    # Tiny async pause to keep the event loop responsive.
    await _asyncio_sleep(0.01)


async def _asyncio_sleep(delay: float):
    import asyncio

    await asyncio.sleep(delay)


def chat_completion_response(
    chunk_iterable: Iterable[str],
    model: str,
    prompt_messages: Optional[List[str]] = None,
    created: Optional[int] = None,
    completion_id: Optional[str] = None,
):
    """
    Build a full ChatCompletions response from an iterable of text chunks.
    Token counts are rough (word splits); replace with a real tokenizer if needed.
    """
    created_ts, cid = _default_ids(created, completion_id)
    content = "".join(chunk_iterable)
    prompt_text = " ".join(prompt_messages or [])
    prompt_tokens = len(prompt_text.split()) if prompt_text else 0
    completion_tokens = len(content.split())

    return {
        "id": cid,
        "object": "chat.completion",
        "created": created_ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }

