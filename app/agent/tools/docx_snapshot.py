"""Tool: Build a paragraph-level snapshot of a .docx for format instructions.

The snapshot is what the LLM sees when interpreting a natural-language
formatting instruction: for every paragraph it provides the text, a semantic
role (heading/body/list/quote), and the current formatting so the LLM can
decide which paragraphs to target and what values to change.
"""

import io
import zipfile
from typing import Any

import mammoth
from bs4 import BeautifulSoup
from lxml import etree

from app.agent.tools.content_analyzer import _parse_html_structure
from app.agent.tools.docx_parser import (
    _parse_paragraph_props,
    _parse_run_props,
    _q,
)


def build_snapshot(docx_bytes: bytes) -> dict[str, Any]:
    """Build a paragraph snapshot from raw .docx bytes.

    Args:
        docx_bytes: Raw .docx file bytes.

    Returns:
        {"paragraphs": [...], "paragraph_count": N}. Each paragraph carries
        index, text, semantic_role, html_tag and a formatting dict.
    """
    # 1. Semantic roles via mammoth → HTML (reuse content_analyzer logic)
    with io.BytesIO(docx_bytes) as f:
        html = mammoth.convert_to_html(f).value
    soup = BeautifulSoup(html, "html.parser")
    html_paras = _parse_html_structure(soup)

    # 2. Paragraph text + current formatting via lxml on document.xml
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as z:
        doc_xml = z.read("word/document.xml")

    tree = etree.fromstring(doc_xml)
    body = tree.find(_q("body"))
    if body is None:
        return {"paragraphs": [], "paragraph_count": 0}

    paragraphs: list[dict[str, Any]] = []
    for i, p_elem in enumerate(body.findall(_q("p"))):
        text = "".join(t.text or "" for t in p_elem.iter(_q("t"))).strip()

        role = "paragraph"
        tag = "p"
        if i < len(html_paras):
            role = html_paras[i].get("semantic_role") or "paragraph"
            tag = html_paras[i].get("tag") or "p"

        paragraphs.append({
            "index": i,
            "text": text[:100],
            "semantic_role": role,
            "html_tag": tag,
            "formatting": _extract_para_format(p_elem),
        })

    return {"paragraphs": paragraphs, "paragraph_count": len(paragraphs)}


def _extract_para_format(p_elem) -> dict[str, Any]:
    """Read the current effective-ish formatting of a paragraph element.

    Reads direct paragraph/run properties plus the paragraph style name.
    Reuses docx_parser's property readers for consistency.
    """
    fmt: dict[str, Any] = {}

    pPr = p_elem.find(_q("pPr"))
    if pPr is not None:
        pStyle = pPr.find(_q("pStyle"))
        if pStyle is not None:
            fmt["style_name"] = pStyle.get(_q("val"))
        _parse_paragraph_props(pPr, fmt)

    for r_elem in p_elem.iter(_q("r")):
        rPr = r_elem.find(_q("rPr"))
        if rPr is not None:
            _parse_run_props(rPr, fmt)
            break

    # Normalize alignment to lowercase for friendlier LLM consumption.
    if "alignment" in fmt:
        fmt["alignment"] = fmt["alignment"].lower()

    return fmt
