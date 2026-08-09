import base64
import mimetypes

import httpx

from app.config import Settings

IMAGE_DESCRIPTION_TIMEOUT_SECONDS = 120.0


class ImageDescriptionError(Exception):
    pass


def _data_url(filename: str, content_type: str | None, raw: bytes) -> str:
    mime = content_type if content_type and content_type.startswith("image/") else None
    if mime is None:
        mime = mimetypes.guess_type(filename)[0] or "image/png"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def describe_image(
    settings: Settings, filename: str, content_type: str | None, raw: bytes, prompt: str | None = None
) -> str:
    """Calls LM Studio's OpenAI-compatible /v1/chat/completions endpoint with
    a vision-capable model to get a text description of an image, since
    there's no text to chunk/embed directly from raw image bytes. `prompt`
    defaults to vision_description_prompt; describe_pdf_pages below passes
    pdf_ocr_prompt instead, since transcribing a scanned page calls for
    different instructions than describing a photo."""
    data_url = _data_url(filename, content_type, raw)

    try:
        async with httpx.AsyncClient(timeout=IMAGE_DESCRIPTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.vision_lmstudio_base_url}/v1/chat/completions",
                json={
                    "model": settings.vision_lmstudio_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt or settings.vision_description_prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                },
            )
    except httpx.RequestError as exc:
        raise ImageDescriptionError(
            f"Could not reach LM Studio at {settings.vision_lmstudio_base_url}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise ImageDescriptionError(f"LM Studio returned {response.status_code}: {response.text}")

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ImageDescriptionError("Unexpected response shape from LM Studio") from exc


async def describe_pdf_pages(settings: Settings, filename: str, page_images: list[bytes]) -> str:
    """Transcribes each rasterized PDF page (see app/pdf_render.py) via the
    vision model and joins them into one text, for scanned PDFs whose
    extract_text() came back empty because there's no text layer to pull
    from directly."""
    descriptions = [
        await describe_image(
            settings, f"{filename}#page-{index + 1}.png", "image/png", png_bytes, prompt=settings.pdf_ocr_prompt
        )
        for index, png_bytes in enumerate(page_images)
    ]
    return "\n\n".join(f"[Page {index + 1}]\n{description}" for index, description in enumerate(descriptions))
