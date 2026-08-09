from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.pdf_render import PdfRenderError, render_pdf_pages_to_png


def _pdf_bytes(num_pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_render_pdf_pages_to_png_renders_each_page_as_png():
    images = render_pdf_pages_to_png(_pdf_bytes(2), max_pages=20)

    assert len(images) == 2
    for png_bytes in images:
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_pdf_pages_to_png_caps_at_max_pages():
    images = render_pdf_pages_to_png(_pdf_bytes(3), max_pages=2)

    assert len(images) == 2


def test_render_pdf_pages_to_png_raises_on_unparseable_pdf():
    with pytest.raises(PdfRenderError):
        render_pdf_pages_to_png(b"not a real pdf", max_pages=20)
