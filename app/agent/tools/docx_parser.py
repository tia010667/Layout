"""Tool: Parse .docx template — extract formatting rules from raw XML.

Reads styles.xml directly (bypassing python-docx's lossy API) to get
complete and accurate font, paragraph, and spacing properties for every
named style in the template.
"""

import zipfile
import io
from typing import Any

from lxml import etree

WPML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _q(tag: str) -> str:
    return f"{{{WPML}}}{tag}"


def parse_docx_template(file_path: str) -> dict[str, Any]:
    """Parse .docx template and extract all style definitions from raw XML.

    Opens the .docx as a ZIP, reads word/styles.xml directly, and
    extracts complete formatting properties for every named style.
    """
    with open(file_path, "rb") as f:
        zip_bytes = f.read()

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        styles_xml = z.read("word/styles.xml")
        doc_xml = z.read("word/document.xml")

    styles_tree = etree.fromstring(styles_xml)
    doc_tree = etree.fromstring(doc_xml)

    # Parse document defaults (docDefaults) — these define the document-wide
    # default font, size, line spacing, etc. that apply to all styles that
    # don't explicitly override them. Without this, the LLM can't see the
    # actual font/size that "Normal" and other base styles will render with.
    doc_defaults: dict[str, Any] = {}
    dd_elem = styles_tree.find(_q("docDefaults"))
    if dd_elem is not None:
        pPrDef = dd_elem.find(_q("pPrDefault"))
        if pPrDef is not None:
            pPr = pPrDef.find(_q("pPr"))
            if pPr is not None:
                _parse_paragraph_props(pPr, doc_defaults)
        rPrDef = dd_elem.find(_q("rPrDefault"))
        if rPrDef is not None:
            rPr = rPrDef.find(_q("rPr"))
            if rPr is not None:
                _parse_run_props(rPr, doc_defaults)

    # Build a dict of all style properties
    all_styles: dict[str, dict] = {}
    for style_elem in styles_tree.findall(f".//{_q('style')}"):
        style_id = style_elem.get(_q("styleId"))
        style_type = style_elem.get(_q("type"), "paragraph")

        name_elem = style_elem.find(_q("name"))
        if name_elem is None:
            continue
        name = name_elem.get(_q("val"))
        if not name:
            continue

        # Skip internal/latent styles
        if name.startswith("_"):
            continue

        props: dict[str, Any] = {
            "style_type": style_type,
            "style_id": style_id,
        }

        # Read base style reference (for inheritance)
        based_on = style_elem.find(_q("basedOn"))
        if based_on is not None:
            props["base_style_id"] = based_on.get(_q("val"))

        # Read paragraph properties
        pPr = style_elem.find(_q("pPr"))
        if pPr is not None:
            _parse_paragraph_props(pPr, props)

        # Read run (font) properties
        rPr = style_elem.find(_q("rPr"))
        if rPr is not None:
            _parse_run_props(rPr, props)

        all_styles[name] = props

    # Resolve inheritance (walk base_style_id chain)
    _resolve_all_inheritance(all_styles)

    # Apply docDefaults to any styles still missing properties.
    # In OOXML, docDefaults is the lowest-priority source — it fills gaps
    # that neither the style itself nor its base style chain defines.
    if doc_defaults:
        for props in all_styles.values():
            for key, val in doc_defaults.items():
                if key not in props:
                    props[key] = val

    # Classify styles
    heading_styles = []
    default_style = None

    for name, props in all_styles.items():
        name_lower = name.lower()
        if any(kw in name_lower for kw in
               ["heading", "title", "标题", "h1", "h2", "h3", "h4", "h5", "h6",
                "h7", "h8", "h9", "subtitle", "副标题"]):
            heading_styles.append(name)
        if name_lower in ("normal", "正文", "body text", "body"):
            default_style = name

    if not default_style:
        for name in all_styles:
            if "normal" in name.lower() or "正文" in name.lower():
                default_style = name
                break
    if not default_style and all_styles:
        # Pick first paragraph-type style
        for name, props in all_styles.items():
            if "paragraph" in str(props.get("style_type", "")).lower():
                default_style = name
                break

    # Extract format profiles from the template's actual paragraphs.
    # This is critical: many documents (especially Chinese academic papers)
    # use DIRECT formatting on paragraphs rather than style definitions.
    # The styles.xml may only contain Word's default styles, while the real
    # font/size/spacing is in direct formatting on document.xml paragraphs.
    format_profiles = _extract_format_profiles(doc_tree, styles_tree)

    return {
        "styles": all_styles,
        "default_style": default_style,
        "heading_styles": heading_styles,
        "total_styles": len(all_styles),
        "format_profiles": format_profiles,
    }


def _parse_paragraph_props(pPr, props: dict) -> None:
    """Extract paragraph-level properties from <w:pPr>."""
    # Alignment
    jc = pPr.find(_q("jc"))
    if jc is not None:
        align_map = {
            "left": "LEFT", "right": "RIGHT", "center": "CENTER",
            "both": "JUSTIFY", "distribute": "JUSTIFY",
        }
        props["alignment"] = align_map.get(
            jc.get(_q("val"), "left"), "LEFT"
        )

    # Spacing
    spacing = pPr.find(_q("spacing"))
    if spacing is not None:
        before = spacing.get(_q("before"))
        if before:
            props["space_before"] = float(before) / 20  # twips → pt
        after = spacing.get(_q("after"))
        if after:
            props["space_after"] = float(after) / 20
        line_val = spacing.get(_q("line"))
        if line_val:
            line_rule = spacing.get(_q("lineRule"), "auto")
            lv = float(line_val)
            if line_rule == "auto":
                props["line_spacing"] = round(lv / 240, 1)  # 240 = 1.0 spacing
            else:
                props["line_spacing"] = round(lv / 20, 1)  # exact

    # Indentation
    ind = pPr.find(_q("ind"))
    if ind is not None:
        first = ind.get(_q("firstLine"))
        if first:
            props["first_line_indent"] = float(first) / 20
        left_val = ind.get(_q("left"))
        if left_val:
            props["left_indent"] = float(left_val) / 20


def _parse_run_props(rPr, props: dict) -> None:
    """Extract font/run-level properties from <w:rPr>."""
    # Font name
    rFonts = rPr.find(_q("rFonts"))
    if rFonts is not None:
        ascii_font = rFonts.get(_q("ascii"))
        if ascii_font:
            props["font_name"] = ascii_font
        else:
            east = rFonts.get(_q("eastAsia"))
            if east:
                props["font_name"] = east
            else:
                hAnsi = rFonts.get(_q("hAnsi"))
                if hAnsi:
                    props["font_name"] = hAnsi

    # Font size
    sz = rPr.find(_q("sz"))
    if sz is not None:
        val = sz.get(_q("val"))
        if val:
            props["font_size"] = float(val) / 2  # half-points → pt

    # Bold
    b = rPr.find(_q("b"))
    if b is not None:
        props["bold"] = b.get(_q("val"), "true") != "false"

    # Italic
    i = rPr.find(_q("i"))
    if i is not None:
        props["italic"] = i.get(_q("val"), "true") != "false"

    # Underline
    u = rPr.find(_q("u"))
    if u is not None:
        props["underline"] = u.get(_q("val"), "single") != "none"

    # Color
    color = rPr.find(_q("color"))
    if color is not None:
        cval = color.get(_q("val"))
        if cval:
            props["color"] = cval


def _resolve_all_inheritance(all_styles: dict) -> None:
    """Walk inheritance chains and fill in missing properties."""
    # Build style ID → name mapping
    id_to_name: dict[str, str] = {}
    for name, props in all_styles.items():
        sid = props.get("style_id")
        if sid:
            id_to_name[sid] = name

    for name in all_styles:
        _resolve_style_inheritance(name, all_styles, id_to_name, set())


def _resolve_style_inheritance(
    name: str,
    all_styles: dict,
    id_to_name: dict,
    visited: set,
) -> None:
    """Resolve inheritance for a single style recursively."""
    if name in visited:
        return
    visited.add(name)

    props = all_styles.get(name)
    if not props:
        return

    base_id = props.get("base_style_id")
    if not base_id or base_id not in id_to_name:
        return

    base_name = id_to_name[base_id]
    _resolve_style_inheritance(base_name, all_styles, id_to_name, visited)

    base = all_styles.get(base_name)
    if not base:
        return

    # Inherit font properties
    for key in ("font_name", "font_size", "bold", "italic", "underline", "color"):
        if key not in props and key in base:
            props[key] = base[key]

    # Inherit paragraph properties
    for key in ("alignment", "space_before", "space_after", "line_spacing",
                "first_line_indent", "left_indent"):
        if key not in props and key in base:
            props[key] = base[key]


# ---------------------------------------------------------------------------
# Format Profile Extraction — reads document.xml to get REAL formatting
# ---------------------------------------------------------------------------

def _extract_format_profiles(doc_tree, styles_tree) -> list[dict[str, Any]]:
    """Extract format profiles from the template's actual paragraphs.

    A format profile represents one visual format type in the template
    (e.g., title, heading, body text, list item). Each profile captures
    the complete effective formatting (style + direct) so it can be
    applied directly to output paragraphs.

    This is essential because many documents use direct formatting instead
    of style definitions — the styles.xml may only have Word defaults while
    the real font/size/spacing lives in paragraph-level direct formatting.
    """
    body = doc_tree.find(_q("body"))
    if body is None:
        return []

    # Build style ID → raw pPr/rPr XML map
    style_map: dict[str, dict] = {}
    for s in styles_tree.findall(f".//{_q('style')}"):
        sid = s.get(_q("styleId"))
        if not sid:
            continue
        entry: dict[str, Any] = {}
        pPr = s.find(_q("pPr"))
        if pPr is not None:
            entry["pPr"] = pPr
        rPr = s.find(_q("rPr"))
        if rPr is not None:
            entry["rPr"] = rPr
        style_map[sid] = entry

    # Parse each non-empty paragraph's effective formatting
    para_formats: list[dict[str, Any]] = []
    for i, p in enumerate(body.findall(_q("p"))):
        text = "".join(t.text or "" for t in p.iter(_q("t"))).strip()
        if not text:
            continue

        fmt = _extract_para_effective_format(p, style_map)
        fmt["text"] = text[:60]
        fmt["para_index"] = i
        para_formats.append(fmt)

    # Group into format profiles (unique formatting combinations)
    return _group_into_profiles(para_formats)


def _extract_para_effective_format(p_elem, style_map: dict) -> dict[str, Any]:
    """Extract the effective formatting of a paragraph.

    Combines: style definition pPr/rPr + direct pPr/rPr from the paragraph
    and its first run. Returns both readable properties and raw XML elements
    that can be directly applied to output paragraphs.
    """
    result: dict[str, Any] = {}

    pPr = p_elem.find(_q("pPr"))
    pStyle_val = None
    direct_pPr_children: list = []

    if pPr is not None:
        pStyle = pPr.find(_q("pStyle"))
        if pStyle is not None:
            pStyle_val = pStyle.get(_q("val"))

        for child in pPr:
            if _strip_ns(child.tag) != "pStyle":
                direct_pPr_children.append(child)

    result["style_id"] = pStyle_val

    # Get first run's rPr as representative font format
    first_rPr = None
    for r in p_elem.iter(_q("r")):
        rPr = r.find(_q("rPr"))
        if rPr is not None:
            first_rPr = rPr
            break

    # Build combined pPr (style pPr + direct pPr, direct overrides)
    combined_pPr = etree.Element(_q("pPr"))
    if pStyle_val and pStyle_val in style_map:
        style_pPr = style_map[pStyle_val].get("pPr")
        if style_pPr is not None:
            for child in style_pPr:
                if _strip_ns(child.tag) != "pStyle":
                    combined_pPr.append(_clone(child))

    for child in direct_pPr_children:
        tag = child.tag
        for existing in combined_pPr.findall(tag):
            combined_pPr.remove(existing)
        combined_pPr.append(_clone(child))

    # Build combined rPr (style rPr + direct run rPr, direct overrides)
    combined_rPr = etree.Element(_q("rPr"))
    if pStyle_val and pStyle_val in style_map:
        style_rPr = style_map[pStyle_val].get("rPr")
        if style_rPr is not None:
            for child in style_rPr:
                combined_rPr.append(_clone(child))

    if first_rPr is not None:
        for child in first_rPr:
            tag = child.tag
            for existing in combined_rPr.findall(tag):
                combined_rPr.remove(existing)
            combined_rPr.append(_clone(child))

    result["formatting"] = _parse_readable_props(combined_pPr, combined_rPr)
    result["combined_pPr"] = combined_pPr
    result["combined_rPr"] = combined_rPr
    return result


def _parse_readable_props(pPr, rPr) -> dict[str, Any]:
    """Parse human-readable formatting properties from combined pPr/rPr."""
    props: dict[str, Any] = {}

    if pPr is not None:
        for child in pPr:
            tag = _strip_ns(child.tag)
            attrs = {_strip_ns(k): v for k, v in child.attrib.items()}
            if tag == "spacing":
                if "line" in attrs:
                    line_rule = attrs.get("lineRule", "auto")
                    lv = float(attrs["line"])
                    if line_rule == "auto":
                        props["line_spacing"] = round(lv / 240, 2)
                    else:
                        props["line_spacing"] = round(lv / 20, 1)
                if "before" in attrs:
                    props["space_before"] = round(float(attrs["before"]) / 20, 1)
                if "after" in attrs:
                    props["space_after"] = round(float(attrs["after"]) / 20, 1)
            elif tag == "ind":
                if "firstLine" in attrs:
                    props["first_line_indent"] = round(float(attrs["firstLine"]) / 20, 1)
                if "left" in attrs:
                    props["left_indent"] = round(float(attrs["left"]) / 20, 1)
            elif tag == "jc":
                props["alignment"] = attrs.get("val", "left").upper()
            elif tag == "numPr":
                props["has_numbering"] = True

    if rPr is not None:
        for child in rPr:
            tag = _strip_ns(child.tag)
            attrs = {_strip_ns(k): v for k, v in child.attrib.items()}
            if tag == "rFonts":
                font = attrs.get("ascii") or attrs.get("eastAsia") or attrs.get("hAnsi")
                if font:
                    props["font_name"] = font
                elif "asciiTheme" in attrs:
                    props["font_theme"] = attrs["asciiTheme"]
            elif tag == "sz":
                props["font_size"] = float(attrs.get("val", "0")) / 2
            elif tag == "b":
                props["bold"] = attrs.get("val", "true") != "false"
            elif tag == "i":
                props["italic"] = attrs.get("val", "true") != "false"
            elif tag == "color":
                props["color"] = attrs.get("val")

    return props


def _group_into_profiles(para_formats: list[dict]) -> list[dict[str, Any]]:
    """Group paragraphs with identical formatting into format profiles."""
    profiles: list[dict[str, Any]] = []
    seen_keys: dict = {}

    for pf in para_formats:
        fmt = pf["formatting"]
        key = (
            fmt.get("font_name", ""),
            fmt.get("font_size", 0),
            fmt.get("line_spacing", ""),
            fmt.get("left_indent", 0),
            fmt.get("first_line_indent", 0),
            fmt.get("alignment", ""),
            fmt.get("bold", False),
            fmt.get("has_numbering", False),
        )

        if key not in seen_keys:
            profile_id = f"profile_{len(profiles)}"
            role = _infer_role(fmt, pf["text"])

            # Serialize the combined pPr/rPr for later application
            pPr_xml = etree.tostring(pf["combined_pPr"], encoding="unicode")
            rPr_xml = etree.tostring(pf["combined_rPr"], encoding="unicode")

            profile = {
                "profile_id": profile_id,
                "role": role,
                "formatting": fmt,
                "sample_text": pf["text"],
                "pPr_xml": pPr_xml,
                "rPr_xml": rPr_xml,
                "paragraph_indices": [pf["para_index"]],
            }
            seen_keys[key] = profile
            profiles.append(profile)
        else:
            seen_keys[key]["paragraph_indices"].append(pf["para_index"])

    return profiles


def _infer_role(fmt: dict, text: str) -> str:
    """Infer the semantic role of a paragraph from formatting and text."""
    font_size = fmt.get("font_size", 0)
    has_numbering = fmt.get("has_numbering", False)

    if fmt.get("alignment") == "CENTER" and len(text) < 30:
        return "title"
    if font_size and font_size >= 14 and (has_numbering or len(text) < 20):
        return "heading"
    if has_numbering:
        return "list_item"
    return "body"


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _clone(elem):
    """Deep clone an lxml element."""
    return etree.fromstring(etree.tostring(elem))
