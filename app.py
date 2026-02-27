import os
import uuid
import time
import httpx
import json
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# --- Configuration ---
PORT = int(os.getenv("PORT", 5050))
BACKEND_URL = os.getenv("BACKEND_URL", None) # e.g., http://localhost:8000/v1/chat/completions

app = FastAPI(title="Minimal Inference Gateway")

# --- Schemas (OpenAI Spec) ---
class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    stream: Optional[bool] = False
    model: Optional[str] = "mock-model"

# --- Helper Functions ---
def generate_echo_response(prompt: str, request_id: str) -> Dict[str, Any]:
    """Creates a static OpenAI-style response for the 'echo' mode."""
    content = f"Echo: {prompt}"
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "gateway-echo",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": len(prompt.split()),
            "completion_tokens": len(content.split()),
            "total_tokens": len(prompt.split()) + len(content.split())
        }
    }

async def mock_stream_generator(prompt: str, request_id: str):
    """Simulates an SSE stream for the 'echo' mode."""
    tokens = f"Echo: {prompt}".split()
    for i, token in enumerate(tokens):
        chunk = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "gateway-echo",
            "choices": [{
                "index": 0,
                "delta": {"content": token + " "},
                "finish_reason": None
            }]
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.1) # Simulate network/inference latency
    yield "data: [DONE]\n\n"

# --- Main Route ---
@app.post("/v1/chat/completions")
async def chat_completions(request: Request, body: ChatCompletionRequest):
    # 1. Handle Request ID
    request_id = request.headers.get("X-Request-ID") or request.headers.get("Request-Id") or str(uuid.uuid4())
    
    # 2. Extract Prompt (last user message)
    user_messages = [m.content for m in body.messages if m.role == "user"]
    prompt = user_messages[-1] if user_messages else ""

    # 3. CASE A: No Backend Configured (Echo Mode)
    if not BACKEND_URL:
        if body.stream:
            return StreamingResponse(
                mock_stream_generator(prompt, request_id), 
                media_type="text/event-stream",
                headers={"X-Request-ID": request_id}
            )
        return Response(
            content=json.dumps(generate_echo_response(prompt, request_id)),
            media_type="application/json",
            headers={"X-Request-ID": request_id}
        )

    # 4. CASE B: Backend Proxying
    async with httpx.AsyncClient() as client:
        try:
            # Prepare headers to forward
            headers = {"X-Request-ID": request_id, "Content-Type": "application/json"}
            
            if body.stream:
                # Proxying a Stream
                async def stream_proxy():
                    async with client.stream("POST", BACKEND_URL, json=body.dict(), headers=headers, timeout=60.0) as r:
                        async for chunk in r.aiter_lines():
                            if chunk:
                                yield f"{chunk}\n\n"
                
                return StreamingResponse(stream_proxy(), media_type="text/event-stream")
            
            else:
                # Proxying a Standard Response
                resp = await client.post(BACKEND_URL, json=body.dict(), headers=headers, timeout=60.0)
                resp.raise_for_status()
                return Response(
                    content=resp.content, 
                    status_code=resp.status_code,
                    headers={"X-Request-ID": request_id},
                    media_type="application/json"
                )

        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Backend unreachable: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)