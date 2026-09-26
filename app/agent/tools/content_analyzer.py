"""Tool: Analyze content .docx file — extract paragraph structure.

Uses both mammoth (HTML semantic conversion) and python-docx
(raw paragraph properties) to build a comprehensive content structure.
"""

import re
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


# ============================================================
# Markdown content analysis
# ============================================================

# Inline markdown tokens, in priority order:
#   **bold** / __bold__  (2-char delimiters first)
#   *italic* / _italic_  (1-char, not adjacent to word chars)
#   ~~strikethrough~~
#   `inline code`
_INLINE_TOKEN_RE = re.compile(
    r"(\*\*|__)(.+?)\1"                    # bold (2-char delimiter, matched first)
    r"|(\*|_)([^*_\n]+?)\3"                # italic (single-char delimiter)
    r"|~~(.+?)~~"                           # strikethrough
    r"|`([^`\n]+?)`"                        # inline code
)


def analyze_content_md(file_path: str) -> dict[str, Any]:
    """Parse a content .md (Markdown) file and extract paragraph structure.

    Produces the same shape as :func:`analyze_content_docx` so downstream
    nodes (match_styles, generate_docx) can treat both uniformly. Each
    paragraph additionally carries an inline ``runs`` list so the generator
    can preserve bold/italic/underline formatting.

    Args:
        file_path: Path to the content .md file.

    Returns:
        A dict with 'paragraphs' list and metadata.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    paragraphs = _parse_markdown_blocks(raw_text)

    return {
        "paragraphs": paragraphs,
        "paragraph_count": len(paragraphs),
        "non_empty_count": sum(1 for p in paragraphs if not p["is_empty"]),
        "has_tables": False,
        "has_lists": any(p["semantic_role"] == "list_item" for p in paragraphs),
    }


def _parse_markdown_blocks(text: str) -> list[dict]:
    """Split raw Markdown text into block-level paragraphs."""
    lines = text.split("\n")
    n = len(lines)
    paragraphs: list[dict] = []
    index = 0
    i = 0

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Blank line → paragraph separator
        if not stripped:
            i += 1
            continue

        # Fenced code block (``` or ~~~)
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code = "\n".join(buf).rstrip()
            if code:
                runs = [{"text": code, "bold": False, "italic": False, "underline": False}]
                paragraphs.append(_make_md_para(index, code, "code", "pre", runs))
                index += 1
            continue

        # ATX heading: # ~ ######
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            raw = _strip_links(m.group(2).strip())
            plain, runs, hb, hi = _parse_inline(raw)
            paragraphs.append(
                _make_md_para(index, plain, f"heading_h{level}", f"h{level}", runs, hb, hi)
            )
            index += 1
            i += 1
            continue

        # Blockquote: > ...
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            raw = _strip_links(" ".join(buf))
            plain, runs, hb, hi = _parse_inline(raw)
            paragraphs.append(_make_md_para(index, plain, "quote", "blockquote", runs, hb, hi))
            index += 1
            continue

        # Unordered list item: - / * / +
        m = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if m:
            raw = _strip_links(m.group(1).strip())
            plain, runs, hb, hi = _parse_inline(raw)
            paragraphs.append(_make_md_para(index, plain, "list_item", "li", runs, hb, hi))
            index += 1
            i += 1
            continue

        # Ordered list item: 1. / 2) etc.
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            raw = _strip_links(m.group(1).strip())
            plain, runs, hb, hi = _parse_inline(raw)
            paragraphs.append(_make_md_para(index, plain, "list_item", "li", runs, hb, hi))
            index += 1
            i += 1
            continue

        # Regular paragraph — accumulate until blank line or next block start
        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not _is_md_block_start(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        raw = _strip_links(" ".join(buf))
        plain, runs, hb, hi = _parse_inline(raw)
        paragraphs.append(_make_md_para(index, plain, "paragraph", "p", runs, hb, hi))
        index += 1

    return paragraphs


def _is_md_block_start(line: str) -> bool:
    """Return True if a line begins a new block-level element."""
    s = line.lstrip()
    if not s:
        return False
    return (
        s.startswith("#")
        or s.startswith("```")
        or s.startswith("~~~")
        or s.startswith(">")
        or bool(re.match(r"^\s*[-*+]\s+", line))
        or bool(re.match(r"^\s*\d+[.)]\s+", line))
    )


def _strip_links(text: str) -> str:
    """Remove Markdown link/image syntax, keeping the label text."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)  # ![alt](url) → alt
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)    # [text](url) → text
    return text


def _parse_inline(text: str) -> tuple[str, list[dict], bool, bool]:
    """Split inline Markdown into runs, extracting bold/italic/underline.

    Returns ``(plain_text, runs, has_bold, has_italic)`` where each run is a
    dict ``{"text", "bold", "italic", "underline"}``.
    """
    runs: list[dict] = []
    has_bold = False
    has_italic = False
    last = 0

    for m in _INLINE_TOKEN_RE.finditer(text):
        if m.start() > last:
            runs.append({"text": text[last:m.start()], "bold": False, "italic": False, "underline": False})

        if m.group(1) is not None:  # bold
            runs.append({"text": m.group(2), "bold": True, "italic": False, "underline": False})
            has_bold = True
        elif m.group(3) is not None:  # italic
            runs.append({"text": m.group(4), "bold": False, "italic": True, "underline": False})
            has_italic = True
        elif m.group(5) is not None:  # strikethrough → render as underline
            runs.append({"text": m.group(5), "bold": False, "italic": False, "underline": True})
        elif m.group(6) is not None:  # inline code → plain
            runs.append({"text": m.group(6), "bold": False, "italic": False, "underline": False})

        last = m.end()

    if last < len(text):
        runs.append({"text": text[last:], "bold": False, "italic": False, "underline": False})

    plain = "".join(r["text"] for r in runs)
    return plain, runs, has_bold, has_italic


def _make_md_para(
    index: int,
    text: str,
    semantic_role: str,
    html_tag: str,
    runs: list[dict],
    has_bold: bool = False,
    has_italic: bool = False,
) -> dict:
    """Build a paragraph dict matching the shape produced for .docx content."""
    return {
        "index": index,
        "text": text,
        "word_count": len(text.split()) if text else 0,
        "current_style": None,
        "semantic_role": semantic_role,
        "html_tag": html_tag,
        "has_bold": has_bold,
        "has_italic": has_italic,
        "is_empty": len(text) == 0,
        "runs": runs,
    }
