from io import BytesIO

import pypdfium2 as pdfium

RENDER_SCALE = 2.0


class PdfRenderError(Exception):
    pass


def render_pdf_pages_to_png(raw: bytes, max_pages: int) -> list[bytes]:
    """Rasterizes up to max_pages pages of a PDF to PNG bytes, for feeding
    scanned/text-less pages to the vision model (see describe_pdf_pages in
    app/image_description.py) since there's no text layer to extract
    directly in that case."""
    try:
        pdf = pdfium.PdfDocument(raw)
    except pdfium.PdfiumError as exc:
        raise PdfRenderError(f"Could not open PDF for rendering: {exc}") from exc

    try:
        images = []
        for index in range(min(len(pdf), max_pages)):
            page = pdf[index]
            bitmap = page.render(scale=RENDER_SCALE)
            buf = BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            images.append(buf.getvalue())
        return images
    except pdfium.PdfiumError as exc:
        raise PdfRenderError(f"Could not render PDF pages: {exc}") from exc
    finally:
        pdf.close()
