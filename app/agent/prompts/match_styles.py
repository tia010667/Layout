"""Prompt builder for the match_styles LLM node."""

import json
from typing import Optional

from app.agent.prompts.system import SYSTEM_PROMPT


def build_match_styles_prompt(
    template_analysis: dict,
    content_structure: dict,
    feedback: Optional[str] = None,
) -> list[dict]:
    """Build the message list for the match_styles LLM call.

    Args:
        template_analysis: Parsed template format rules.
        content_structure: Parsed content paragraph structure.
        feedback: Optional verification feedback from a previous attempt.

    Returns:
        List of message dicts for the LLM chat API.
    """
    # Format template format profiles for LLM consumption
    profiles_desc = _format_template_profiles(template_analysis)

    # Format content paragraphs
    paragraphs_desc = _format_content_paragraphs(content_structure)

    user_message = f"""## Available Template Format Profiles

{profiles_desc}

## Content Paragraphs to Map

{paragraphs_desc}

## Instructions

Map each paragraph to the single most appropriate format profile (by profile_id).
Assign a confidence score (0.0-1.0) to each mapping.
The "default_profile_id" should be set to the most common body text profile.
"""

    if feedback:
        retry_section = f"""## Previous Attempt Feedback (FIX THESE ISSUES)

The previous mapping failed verification. Please correct the following issues:

{feedback}

Pay special attention to these problems and ensure they are resolved.
"""
        user_message = user_message + "\n" + retry_section

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def _format_template_profiles(analysis: dict) -> str:
    """Pretty-format the template format profiles for LLM consumption."""
    lines = []
    profiles = analysis.get("format_profiles", [])

    if not profiles:
        return "No format profiles found in template."

    for p in profiles:
        fmt = p.get("formatting", {})
        lines.append(f"### Profile: \"{p['profile_id']}\" (role: {p.get('role', 'unknown')})")
        lines.append(f"  Sample text: {p.get('sample_text', 'N/A')}")
        lines.append(
            f"  Font: {fmt.get('font_name', 'N/A')} "
            f"{fmt.get('font_size', 'N/A')}pt "
            f"(Bold: {fmt.get('bold', False)}, "
            f"Italic: {fmt.get('italic', False)})"
        )
        if fmt.get('color'):
            lines.append(f"  Color: #{fmt['color']}")
        lines.append(f"  Alignment: {fmt.get('alignment', 'N/A')}")
        lines.append(
            f"  Spacing: before={fmt.get('space_before')}, "
            f"after={fmt.get('space_after')}, "
            f"line={fmt.get('line_spacing')}"
        )
        if fmt.get('first_line_indent'):
            lines.append(f"  First line indent: {fmt['first_line_indent']}pt")
        if fmt.get('left_indent'):
            lines.append(f"  Left indent: {fmt['left_indent']}pt")
        if fmt.get('has_numbering'):
            lines.append(f"  Has numbering/list: Yes")
        lines.append("")

    return "\n".join(lines)


def _format_content_paragraphs(structure: dict) -> str:
    """Format content paragraphs for LLM, truncating long text."""
    lines = []
    paragraphs = structure.get("paragraphs", [])

    for p in paragraphs:
        text = p.get("text", "")
        # Truncate long text to save tokens
        if len(text) > 300:
            text = text[:300] + "..."

        role = p.get("semantic_role") or "unknown"
        current_style = p.get("current_style") or "none"

        lines.append(
            f"[Paragraph {p['index']}] "
            f"(current_style={current_style}, "
            f"words={p['word_count']}, "
            f"html_tag={p.get('html_tag', 'none')}, "
            f"role={role})"
        )

        if text:
            lines.append(f"  Text: {text}")
        else:
            lines.append("  Text: [EMPTY PARAGRAPH]")

        if p.get("has_bold"):
            lines.append("  Note: Contains bold inline formatting")
        if p.get("has_italic"):
            lines.append("  Note: Contains italic inline formatting")

        lines.append("")

    return "\n".join(lines)
