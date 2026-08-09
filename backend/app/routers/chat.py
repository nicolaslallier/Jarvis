import httpx
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas import ChatMessage, ChatRequest, ChatResponse

router = APIRouter()

LMSTUDIO_TIMEOUT_SECONDS = 120.0


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    settings = get_settings()
    payload = {
        "model": settings.lmstudio_model,
        "messages": [m.model_dump() for m in request.messages],
    }

    try:
        async with httpx.AsyncClient(timeout=LMSTUDIO_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.lmstudio_base_url}/v1/chat/completions", json=payload
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach LM Studio at {settings.lmstudio_base_url}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"LM Studio returned {response.status_code}: {response.text}"
        )

    data = response.json()
    try:
        choice = data["choices"][0]["message"]
        content = choice["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Unexpected response shape from LM Studio") from exc

    return ChatResponse(message=ChatMessage(role="assistant", content=content))
