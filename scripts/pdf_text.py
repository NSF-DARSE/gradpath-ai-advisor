"""Shared PDF text extraction helpers."""

from pathlib import Path

from pypdf import PdfReader


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract concatenated text from all pages in a PDF."""
    reader = PdfReader(str(pdf_path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n".join(page for page in pages if page)
