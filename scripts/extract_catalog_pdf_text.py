"""Extract catalog PDF text to a reusable text artifact."""

from pathlib import Path

from .pdf_text import extract_pdf_text


PACKAGE_DIR = Path(__file__).resolve().parent.parent
CATALOGS_DIR = PACKAGE_DIR / "data" / "catalogs"
SOURCE_PDF = CATALOGS_DIR / "2025_26-Catalog_1282026.pdf"
OUTPUT_TEXT = CATALOGS_DIR / "2025_26-Catalog_1282026.txt"


def extract_catalog_text() -> Path:
    """Extract the main catalog PDF into a text file for one-time reuse."""
    OUTPUT_TEXT.write_text(extract_pdf_text(SOURCE_PDF), encoding="utf-8")
    return OUTPUT_TEXT


if __name__ == "__main__":
    print(extract_catalog_text())
