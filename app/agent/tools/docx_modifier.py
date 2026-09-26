"""Tool: Apply format operations to a .docx file's document.xml.

Each operation targets a list of paragraph indices and sets one or more
format properties. Values are expressed in human-readable units (pt for
size/indent/spacing, multiplier for line spacing); this module handles all
OOXML conversions (half-points, twips, line=240*n).
"""

import io
import zipfile
from typing import Any

from lxml import etree

WPML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{WPML}}}{tag}"


# Properties that live in <w:pPr> (paragraph-level)
_PARAGRAPH_PROPS = {
    "alignment", "line_spacing", "space_before", "space_after",
    "first_line_indent", "left_indent",
}
# Properties that live in <w:rPr> (run-level)
_RUN_PROPS = {
    "font_name", "font_size", "bold", "italic", "underline", "color",
}


def apply_operations(docx_bytes: bytes, operations: list[dict]) -> bytes:
    """Apply a list of format operations and return new .docx bytes.

    Args:
        docx_bytes: Raw .docx file bytes.
        operations: List of dicts, each
            {"paragraph_indices": [int], "set": {"font_size": 16, ...}}.

    Returns:
        New .docx bytes with the operations applied.
    """
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as z:
        doc_xml = z.read("word/document.xml")

    tree = etree.fromstring(doc_xml)
    body = tree.find(_q("body"))
    if body is None:
        raise ValueError("No body element in document")

    all_ps = body.findall(_q("p"))

    for op in operations:
        indices = op.get("paragraph_indices", [])
        changes = op.get("set", {})
        for idx in indices:
            if 0 <= idx < len(all_ps):
                _apply_changes(all_ps[idx], changes)

    new_doc_xml = etree.tostring(
        tree, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    output_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zin, \
            zipfile.ZipFile(output_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "word/document.xml":
                zout.writestr(item, new_doc_xml)
            else:
                zout.writestr(item, zin.read(item.filename))

    return output_buf.getvalue()


def _apply_changes(p_elem, changes: dict) -> None:
    """Apply property changes to a single paragraph element."""
    pPr_changes = {k: v for k, v in changes.items() if k in _PARAGRAPH_PROPS}
    rPr_changes = {k: v for k, v in changes.items() if k in _RUN_PROPS}

    if pPr_changes:
        _apply_pPr_changes(_ensure_pPr(p_elem), pPr_changes)

    if rPr_changes:
        runs = p_elem.findall(_q("r"))
        if not runs:
            # No runs yet — create an empty run so run formatting can land.
            runs = [etree.SubElement(p_elem, _q("r"))]
        for r_elem in runs:
            _apply_rPr_changes(_ensure_child(r_elem, _q("rPr")), rPr_changes)


def _ensure_pPr(p_elem):
    """Return the paragraph's <w:pPr>, creating it as the first child if absent."""
    pPr = p_elem.find(_q("pPr"))
    if pPr is None:
        pPr = etree.Element(_q("pPr"))
        p_elem.insert(0, pPr)
    return pPr


def _ensure_child(parent, tag):
    """Return the first child with the given tag, creating it if absent."""
    child = parent.find(tag)
    if child is None:
        child = etree.SubElement(parent, tag)
    return child


def _apply_pPr_changes(pPr, changes: dict) -> None:
    # alignment → <w:jc>
    if "alignment" in changes:
        align_map = {
            "left": "left", "center": "center", "right": "right",
            "justify": "both", "both": "both",
        }
        jc = _ensure_child(pPr, _q("jc"))
        jc.set(_q("val"), align_map.get(str(changes["alignment"]).lower(), "left"))

    # line_spacing / space_before / space_after → <w:spacing>
    if any(k in changes for k in ("line_spacing", "space_before", "space_after")):
        spacing = _ensure_child(pPr, _q("spacing"))
        if "line_spacing" in changes:
            n = float(changes["line_spacing"])
            spacing.set(_q("line"), str(int(round(n * 240))))
            spacing.set(_q("lineRule"), "auto")
        if "space_before" in changes:
            spacing.set(_q("before"), str(int(round(float(changes["space_before"]) * 20))))
        if "space_after" in changes:
            spacing.set(_q("after"), str(int(round(float(changes["space_after"]) * 20))))

    # first_line_indent / left_indent → <w:ind>
    if any(k in changes for k in ("first_line_indent", "left_indent")):
        ind = _ensure_child(pPr, _q("ind"))
        if "first_line_indent" in changes:
            ind.set(_q("firstLine"), str(int(round(float(changes["first_line_indent"]) * 20))))
        if "left_indent" in changes:
            ind.set(_q("left"), str(int(round(float(changes["left_indent"]) * 20))))


def _apply_rPr_changes(rPr, changes: dict) -> None:
    # font_name → <w:rFonts>
    if "font_name" in changes:
        rFonts = _ensure_child(rPr, _q("rFonts"))
        name = str(changes["font_name"])
        rFonts.set(_q("ascii"), name)
        rFonts.set(_q("hAnsi"), name)
        rFonts.set(_q("eastAsia"), name)

    # font_size (pt) → <w:sz>/<w:szCs> (half-points)
    if "font_size" in changes:
        half = str(int(round(float(changes["font_size"]) * 2)))
        _ensure_child(rPr, _q("sz")).set(_q("val"), half)
        _ensure_child(rPr, _q("szCs")).set(_q("val"), half)

    # bold / italic / underline
    if "bold" in changes:
        _ensure_child(rPr, _q("b")).set(_q("val"), "true" if _to_bool(changes["bold"]) else "false")
    if "italic" in changes:
        _ensure_child(rPr, _q("i")).set(_q("val"), "true" if _to_bool(changes["italic"]) else "false")
    if "underline" in changes:
        _ensure_child(rPr, _q("u")).set(_q("val"), "single" if _to_bool(changes["underline"]) else "none")

    # color → <w:color> (RRGGBB)
    if "color" in changes:
        _ensure_child(rPr, _q("color")).set(_q("val"), str(changes["color"]).lstrip("#"))


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on", "是")
    return bool(v)
