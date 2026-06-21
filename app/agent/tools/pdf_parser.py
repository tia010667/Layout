"""Tool: Parse PDF template to infer formatting rules.

PDFs don't have named styles like .docx, so we infer formatting
from text blocks — font, size, bold, spacing.
"""

import re
from typing import Any


def parse_pdf_template(file_path: str) -> dict[str, Any]:
    """Parse a PDF template file and infer formatting styles from text blocks.

    Uses pymupdf (fitz) to extract text with positional and font information.
    Groups text blocks by font properties to infer style definitions.

    Args:
        file_path: Path to the PDF template file.

    Returns:
        A dict with inferred 'styles' mapping.
    """
    import fitz  # pymupdf

    doc = fitz.open(file_path)

    # Collect all text spans with font info
    spans = []
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    spans.append({
                        "text": span["text"].strip(),
                        "font": span["font"],
                        "size": round(span["size"], 1),
                        "bold": "bold" in span["font"].lower() or "black" in span["font"].lower(),
                        "italic": "italic" in span["font"].lower() or "oblique" in span["font"].lower(),
                        "color": _extract_color(span.get("color", 0)),
                        "bbox": span["bbox"],
                    })

    doc.close()

    if not spans:
        return {"styles": {}, "default_style": None, "heading_styles": [], "total_styles": 0}

    # Group spans by (font, size, bold) to infer styles
    style_groups = {}
    for span in spans:
        key = (span["font"], span["size"], span["bold"], span["italic"])
        if key not in style_groups:
            style_groups[key] = []
        style_groups[key].append(span)

    # Build style definitions from groups
    styles = {}
    heading_styles = []
    style_idx = 1

    # Sort groups by size descending (largest is usually title/heading)
    sorted_groups = sorted(style_groups.items(), key=lambda x: x[0][1], reverse=True)

    for (font_name, size, bold, italic), group_spans in sorted_groups:
        # Determine style name based on size and formatting
        sample_texts = [s["text"] for s in group_spans[:5] if s["text"]]

        if size >= 18:
            name = f"Title (inferred)"
        elif size >= 14:
            name = f"Heading {style_idx} (inferred)"
            heading_styles.append(name)
        elif bold and size >= 11:
            name = f"Heading {style_idx} (inferred)"
            heading_styles.append(name)
        else:
            name = f"Body Style {style_idx} (inferred)"

        if name in styles:
            name = f"{name} ({style_idx})"

        styles[name] = {
            "font_name": font_name,
            "font_size": size,
            "bold": bold,
            "italic": italic,
            "underline": False,
            "color": group_spans[0]["color"] if group_spans else "000000",
            "alignment": "LEFT",  # Can't reliably infer from PDF
            "space_before": 6 if size >= 14 else 0,
            "space_after": 6 if size >= 14 else 0,
            "line_spacing": 1.5,
            "first_line_indent": None,
            "left_indent": None,
            "sample_count": len(group_spans),
            "sample_texts": sample_texts,
        }
        style_idx += 1

    # Determine default (most common body style)
    default_style = None
    for name in styles:
        if "body" in name.lower() or "normal" in name.lower():
            default_style = name
            break
    if not default_style and styles:
        # Pick the most frequently used style
        default_style = max(styles, key=lambda n: styles[n].get("sample_count", 0))

    return {
        "styles": styles,
        "default_style": default_style,
        "heading_styles": heading_styles,
        "total_styles": len(styles),
        "source": "pdf_inferred",
    }


def _extract_color(color_int: int) -> str:
    """Convert an integer color to hex string."""
    if isinstance(color_int, int):
        return f"{color_int:06X}"
    return "000000"
