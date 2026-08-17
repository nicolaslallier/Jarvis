"""Client for the Obsidian Local REST API plugin
(coddingtonbear/obsidian-local-rest-api), giving app/routers/chat.py's
OBSIDIAN_TOOLS read/write access to the user's Obsidian vault.

The plugin runs inside the user's Obsidian app on the host machine, not in
this Docker network, so OBSIDIAN_BASE_URL defaults to host.docker.internal
(same reasoning as LMSTUDIO_BASE_URL in app/config.py). Every call needs the
plugin's API key as a bearer token; OBSIDIAN_API_KEY empty means the
integration is unconfigured (same "leave it empty to disable" convention as
IMAP_HOST/NTFY_TOPIC) — every function below raises ObsidianNotConfigured
immediately rather than making a request that could only fail.

Every call goes through _request(), which opens its own httpx.AsyncClient per
call (same convention as app/embeddings.py, rather than a persistent client)
and wraps transport-level failures (Obsidian not running, DNS, timeout) into
ObsidianRequestError, so callers get one consistent exception type regardless
of whether the failure was a bad response or a dead connection.
"""

import logging
from urllib.parse import quote

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

OBSIDIAN_TIMEOUT_SECONDS = 15.0


class ObsidianNotConfigured(Exception):
    """OBSIDIAN_API_KEY isn't set — the integration is optional and off."""


class ObsidianRequestError(Exception):
    """The Local REST API call itself failed: a network error (Obsidian
    isn't running, DNS, timeout) or a non-2xx response."""


class ObsidianInvalidPath(Exception):
    """The given vault-relative path attempts to escape the vault root
    (e.g. via a ".." segment) — refused before any request is made, since
    the Local REST API plugin's own traversal handling isn't something
    this backend can verify."""


def _settings_or_raise():
    settings = get_settings()
    if not settings.obsidian_api_key:
        raise ObsidianNotConfigured(
            "Obsidian integration is not configured (OBSIDIAN_API_KEY is empty)."
        )
    return settings


def _headers(settings, **extra: str) -> dict:
    return {"Authorization": f"Bearer {settings.obsidian_api_key}", **extra}


def _confined_path(path: str) -> str:
    """Strips a leading slash and rejects any path whose ".." segments
    would resolve above the vault root, without rejecting harmless
    internal ".." usage (e.g. "a/../b")."""
    trimmed = path.lstrip("/")
    depth = 0
    for segment in trimmed.split("/"):
        if segment in ("", "."):
            continue
        depth = depth - 1 if segment == ".." else depth + 1
        if depth < 0:
            raise ObsidianInvalidPath(f"Path escapes the vault root: {path!r}")
    return trimmed


def _vault_url(settings, path: str) -> str:
    # Percent-encode each path segment (but keep "/" as the separator) so
    # characters like '#' or '?' in a note name aren't parsed by httpx as a
    # URL fragment/query and silently dropped from the request.
    return f"{settings.obsidian_base_url}/vault/{quote(_confined_path(path), safe='/')}"


async def _request(method: str, url: str, *, settings, headers: dict, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
            return await client.request(method, url, headers=headers, **kwargs)
    except httpx.RequestError as exc:
        raise ObsidianRequestError(
            f"Could not reach Obsidian at {settings.obsidian_base_url}: {exc}"
        ) from exc


async def list_notes(dir_path: str = "") -> list[str]:
    """Lists files/subdirectories directly under `dir_path` (vault root if
    empty). Subdirectory entries are returned with a trailing "/"."""
    settings = _settings_or_raise()
    trimmed = dir_path.strip("/")
    url = _vault_url(settings, f"{trimmed}/" if trimmed else "")
    response = await _request("GET", url, settings=settings, headers=_headers(settings))
    if response.status_code != 200:
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")
    return response.json().get("files", [])


async def read_note(path: str) -> str:
    """Returns the raw markdown content of the note at `path` (relative to
    the vault root, e.g. "Journal/2026-08-17.md")."""
    settings = _settings_or_raise()
    response = await _request(
        "GET",
        _vault_url(settings, path),
        settings=settings,
        headers=_headers(settings, Accept="text/markdown"),
    )
    if response.status_code == 404:
        raise ObsidianRequestError(f"No note found at {path}")
    if response.status_code != 200:
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")
    return response.text


async def search_notes(query: str, context_length: int = 100) -> list[dict]:
    """Full-text search across the vault. Each result has `filename`,
    `score`, and `matches` (a list of `{context, match: {start, end}}`)."""
    settings = _settings_or_raise()
    url = f"{settings.obsidian_base_url}/search/simple/"
    response = await _request(
        "POST",
        url,
        settings=settings,
        headers=_headers(settings),
        params={"query": query, "contextLength": context_length},
    )
    if response.status_code != 200:
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")
    return response.json()


async def write_note(path: str, content: str) -> None:
    """Creates the note at `path` if it doesn't exist, or overwrites its
    entire content if it does."""
    settings = _settings_or_raise()
    response = await _request(
        "PUT",
        _vault_url(settings, path),
        settings=settings,
        headers=_headers(settings, **{"Content-Type": "text/markdown"}),
        content=content,
    )
    if response.status_code not in (200, 204):
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")


async def append_note(path: str, content: str) -> None:
    """Appends `content` to the end of the note at `path`, creating it if
    it doesn't exist yet."""
    settings = _settings_or_raise()
    response = await _request(
        "POST",
        _vault_url(settings, path),
        settings=settings,
        headers=_headers(settings, **{"Content-Type": "text/markdown"}),
        content=content,
    )
    if response.status_code not in (200, 204):
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")


async def delete_note(path: str) -> None:
    settings = _settings_or_raise()
    response = await _request(
        "DELETE", _vault_url(settings, path), settings=settings, headers=_headers(settings)
    )
    if response.status_code not in (200, 204):
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")
