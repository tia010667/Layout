"""Node 3: LLM style matching — the core intelligence of FormatAI.

Takes parsed template styles + content structure → LLM call →
produces a structured style mapping with paragraph → style assignments.
"""

import json
import logging
import re
import sys
from typing import Optional

from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.agent.prompts.match_styles import build_match_styles_prompt
from app.config import settings

logger = logging.getLogger(__name__)


# -- Structured Output Schemas --

class StyleMappingEntry(BaseModel):
    """A single paragraph-to-profile mapping."""
    paragraph_index: int = Field(description="Index of the paragraph")
    profile_id: str = Field(description="Exact profile_id from template (e.g. 'profile_0')")
    reasoning: str = Field(description="Why this profile was chosen")
    confidence: float = Field(description="Confidence score 0.0-1.0", ge=0.0, le=1.0)


class StyleMappingOutput(BaseModel):
    """Complete structured output from match_styles LLM call."""
    mappings: list[StyleMappingEntry] = Field(description="List of paragraph-to-profile mappings")
    unmapped_paragraphs: list[int] = Field(default_factory=list, description="Paragraph indices that could not be mapped")
    default_profile_id: str = Field(description="Profile ID for any unmatched paragraphs (usually the most common body profile)")


def _parse_json_output(raw_text: str) -> dict:
    """Try to extract and parse JSON from raw LLM output.

    Handles cases where the LLM wraps JSON in markdown code blocks
    or adds extra text around the JSON.
    """
    # Try direct parse first
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` block
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object boundaries
    match = re.search(r'\{[\s\S]*\}', raw_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM output. First 500 chars: {raw_text[:500]}")


async def match_styles(state: AgentState) -> dict:
    """Execute the LLM style matching node.

    Tries structured output first (function_calling), falls back to
    plain JSON mode if that fails.
    """
    template_analysis = state.get("template_analysis")
    content_structure = state.get("content_structure")
    feedback = state.get("verification_feedback")
    retry_count = state.get("retry_count", 0)
    error_msg = state.get("error")  # Check if there was a prior error

    if not template_analysis:
        return {"error": "No template analysis available", "status": "failed"}
    if not content_structure:
        return {"error": "No content structure available", "status": "failed"}

    # Build the message list
    messages = build_match_styles_prompt(
        template_analysis=template_analysis,
        content_structure=content_structure,
        feedback=feedback,
    )

    para_count = content_structure.get('paragraph_count', 0)
    print(f"\n  [match_styles] Starting (attempt {retry_count + 1}, {para_count} paragraphs)", flush=True)

    from langchain_openai import ChatOpenAI

    # Try approach 1: structured output via function calling
    try:
        llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.1,
            max_tokens=8192,
        )

        structured_llm = llm.with_structured_output(
            StyleMappingOutput,
            method="function_calling",
        )

        print(f"  [match_styles] Calling LLM with function_calling...", flush=True)
        result: StyleMappingOutput = await structured_llm.ainvoke(messages)
        print(f"  [match_styles] Got {len(result.mappings)} mappings", flush=True)

        style_mapping = {
            "mappings": [
                {
                    "paragraph_index": m.paragraph_index,
                    "profile_id": m.profile_id,
                    "reasoning": m.reasoning,
                    "confidence": m.confidence,
                }
                for m in result.mappings
            ],
            "unmapped_paragraphs": result.unmapped_paragraphs,
            "default_profile_id": result.default_profile_id,
        }

        return {
            "style_mapping": style_mapping,
            "status": "verifying",
        }

    except Exception as e1:
        err_str = f"{type(e1).__name__}: {str(e1)}"
        print(f"  [match_styles] Structured output failed: {err_str[:200]}", flush=True)
        logger.warning(f"Structured output failed: {err_str}")

        # Approach 2: plain JSON mode
        try:
            print(f"  [match_styles] Falling back to plain JSON mode...", flush=True)

            llm2 = ChatOpenAI(
                model=settings.deepseek_model,
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                temperature=0.1,
                max_tokens=8192,
            )

            # Add explicit JSON instruction to system prompt
            json_messages = list(messages)
            json_messages.append({
                "role": "user",
                "content": "\n\nIMPORTANT: Output ONLY valid JSON, no markdown formatting, no code blocks. Start with { and end with }."
            })

            raw_response = await llm2.ainvoke(json_messages)
            raw_text = raw_response.content if hasattr(raw_response, 'content') else str(raw_response)
            print(f"  [match_styles] Raw response length: {len(raw_text)} chars", flush=True)

            parsed = _parse_json_output(raw_text)

            # Validate the parsed structure
            if "mappings" not in parsed:
                raise ValueError("Missing 'mappings' in parsed JSON")
            if "default_profile_id" not in parsed:
                # Try to find the most common body profile
                profiles = template_analysis.get("format_profiles", [])
                default_id = "profile_0"
                for p in profiles:
                    if p.get("role") == "body":
                        default_id = p["profile_id"]
                        break
                parsed["default_profile_id"] = default_id

            print(f"  [match_styles] JSON fallback: {len(parsed.get('mappings', []))} mappings", flush=True)

            return {
                "style_mapping": parsed,
                "status": "verifying",
            }

        except Exception as e2:
            err_str2 = f"{type(e2).__name__}: {str(e2)}"
            print(f"  [match_styles] JSON fallback also failed: {err_str2[:200]}", flush=True)
            logger.error(f"Both approaches failed: {err_str} | {err_str2}")

            return {
                "error": f"[match_styles] Both approaches failed: {err_str[:100]} | {err_str2[:100]}",
                "status": "failed",
            }
