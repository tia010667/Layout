"""Tool: Analyze content .docx file — extract paragraph structure.

Uses both mammoth (HTML semantic conversion) and python-docx
(raw paragraph properties) to build a comprehensive content structure.
"""

from typing import Any

import mammoth
from bs4 import BeautifulSoup
from docx import Document


def analyze_content_docx(file_path: str) -> dict[str, Any]:
    """Parse a content .docx file and extract paragraph structure.

    Args:
        file_path: Path to the content .docx file.

    Returns:
        A dict with 'paragraphs' list and metadata.
    """
    doc = Document(file_path)

    # Generate HTML via mammoth for semantic hints
    with open(file_path, "rb") as f:
        mammoth_result = mammoth.convert_to_html(f)
    html = mammoth_result.value

    # Parse HTML for semantic structure
    soup = BeautifulSoup(html, "html.parser")
    html_paragraphs = _parse_html_structure(soup)

    # Read raw DOCX paragraphs for precise details
    paragraphs = []
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        word_count = len(text.split()) if text else 0

        # Get current style
        current_style = para.style.name if para.style else None

        # Check inline formatting from runs
        has_bold = False
        has_italic = False
        for run in para.runs:
            if run.bold:
                has_bold = True
            if run.italic:
                has_italic = True

        # Match with HTML semantic info if available
        semantic_role = None
        html_tag = None
        if i < len(html_paragraphs):
            semantic_role = html_paragraphs[i].get("semantic_role")
            html_tag = html_paragraphs[i].get("tag")

        paragraphs.append({
            "index": i,
            "text": text,
            "word_count": word_count,
            "current_style": current_style,
            "semantic_role": semantic_role,
            "html_tag": html_tag,
            "has_bold": has_bold,
            "has_italic": has_italic,
            "is_empty": word_count == 0,
        })

    # Detect lists and tables
    has_tables = len(doc.tables) > 0
    has_lists = _has_lists(doc)

    # Post-process: mark consecutive empty paragraphs
    _mark_empty_context(paragraphs)

    return {
        "paragraphs": paragraphs,
        "paragraph_count": len(paragraphs),
        "non_empty_count": sum(1 for p in paragraphs if not p["is_empty"]),
        "has_tables": has_tables,
        "has_lists": has_lists,
    }


def _parse_html_structure(soup: BeautifulSoup) -> list[dict]:
    """Extract semantic structure from mammoth HTML output."""
    result = []

    # Collect all block-level elements in order
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote"]):
        text = tag.get_text(strip=True)

        # Determine semantic role from tag
        if tag.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            semantic_role = f"heading_{tag.name}"
        elif tag.name == "li":
            semantic_role = "list_item"
        elif tag.name == "blockquote":
            semantic_role = "quote"
        else:
            semantic_role = "paragraph"

        result.append({
            "tag": tag.name,
            "semantic_role": semantic_role,
            "text": text[:200],
        })

    return result


def _has_lists(doc: Document) -> bool:
    """Detect if the document contains any numbered or bulleted lists."""
    for para in doc.paragraphs:
        if para.style.name and "list" in para.style.name.lower():
            return True
        pPr = para._element.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
        if pPr is not None:
            return True
    return False


def _mark_empty_context(paragraphs: list[dict]) -> None:
    """Mark empty paragraphs that may serve as section breaks."""
    for i, p in enumerate(paragraphs):
        if p["is_empty"] and i > 0 and i < len(paragraphs) - 1:
            prev = paragraphs[i - 1]
            next_p = paragraphs[i + 1]
            if not prev["is_empty"] and not next_p["is_empty"]:
                p["semantic_role"] = "section_break"
