import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_NTFY_TIMEOUT_SECONDS = 10.0


async def send_ntfy(settings: Settings, title: str, message: str, priority: str = "default") -> None:
    """Best-effort push notification via ntfy.sh (or a self-hosted ntfy
    instance). Posts to f"{settings.ntfy_url}/{settings.ntfy_topic}" with the
    notification title in the `Title` header and `message` as the body, per
    ntfy's publish-by-HTTP-POST API.

    ntfy is an optional integration, not a hard dependency — matching this
    codebase's "best-effort external call" convention (see
    backend/app/routers/chat.py's `_embed_text`, which treats LM Studio being
    unreachable as a soft failure rather than a crash). If
    `settings.ntfy_topic` is empty/unset, this logs a warning and no-ops
    instead of raising, so callers never need to guard on whether ntfy is
    configured.
    """
    if not settings.ntfy_topic:
        logger.warning("send_ntfy: NTFY_TOPIC not configured, skipping notification %r", title)
        return

    url = f"{settings.ntfy_url}/{settings.ntfy_topic}"
    try:
        async with httpx.AsyncClient(timeout=_NTFY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url,
                content=message.encode("utf-8"),
                headers={"Title": title, "Priority": priority},
            )
        if response.status_code >= 300:
            logger.warning("send_ntfy: ntfy call returned %s for %r", response.status_code, url)
    except Exception:
        logger.warning("send_ntfy: ntfy call failed", exc_info=True)
