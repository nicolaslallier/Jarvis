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

Each function opens its own httpx.AsyncClient per call, same convention as
app/embeddings.py, rather than a persistent client.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

OBSIDIAN_TIMEOUT_SECONDS = 15.0


class ObsidianNotConfigured(Exception):
    """OBSIDIAN_API_KEY isn't set — the integration is optional and off."""


class ObsidianRequestError(Exception):
    """The Local REST API call itself failed (network error, non-2xx
    response) — e.g. Obsidian isn't running or the plugin is disabled."""


def _settings_or_raise():
    settings = get_settings()
    if not settings.obsidian_api_key:
        raise ObsidianNotConfigured(
            "Obsidian integration is not configured (OBSIDIAN_API_KEY is empty)."
        )
    return settings


def _headers(settings, **extra: str) -> dict:
    return {"Authorization": f"Bearer {settings.obsidian_api_key}", **extra}


def _vault_url(settings, path: str) -> str:
    return f"{settings.obsidian_base_url}/vault/{path.lstrip('/')}"


async def list_notes(dir_path: str = "") -> list[str]:
    """Lists files/subdirectories directly under `dir_path` (vault root if
    empty). Subdirectory entries are returned with a trailing "/"."""
    settings = _settings_or_raise()
    trimmed = dir_path.strip("/")
    url = _vault_url(settings, f"{trimmed}/" if trimmed else "")
    async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=_headers(settings))
    if response.status_code != 200:
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")
    return response.json().get("files", [])


async def read_note(path: str) -> str:
    """Returns the raw markdown content of the note at `path` (relative to
    the vault root, e.g. "Journal/2026-08-17.md")."""
    settings = _settings_or_raise()
    async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
        response = await client.get(
            _vault_url(settings, path), headers=_headers(settings, Accept="text/markdown")
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
    async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
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
    async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
        response = await client.put(
            _vault_url(settings, path),
            headers=_headers(settings, **{"Content-Type": "text/markdown"}),
            content=content,
        )
    if response.status_code not in (200, 204):
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")


async def append_note(path: str, content: str) -> None:
    """Appends `content` to the end of the note at `path`, creating it if
    it doesn't exist yet."""
    settings = _settings_or_raise()
    async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
        response = await client.post(
            _vault_url(settings, path),
            headers=_headers(settings, **{"Content-Type": "text/markdown"}),
            content=content,
        )
    if response.status_code not in (200, 204):
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")


async def delete_note(path: str) -> None:
    settings = _settings_or_raise()
    async with httpx.AsyncClient(timeout=OBSIDIAN_TIMEOUT_SECONDS) as client:
        response = await client.delete(_vault_url(settings, path), headers=_headers(settings))
    if response.status_code not in (200, 204):
        raise ObsidianRequestError(f"Obsidian returned {response.status_code}: {response.text}")
