"""Tool: Interpret a natural-language formatting instruction into operations.

Uses the LLM (structured output) to turn a free-text instruction plus a
paragraph snapshot into a list of concrete FormatOperation objects.
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.agent.nodes.match_styles import _parse_json_output
from app.agent.prompts.format_instruction import build_format_instruction_prompt
from app.config import settings

logger = logging.getLogger(__name__)

# Fields that may be changed on a paragraph. Kept in sync with
# docx_modifier's _PARAGRAPH_PROPS / _RUN_PROPS.
PROPERTY_FIELDS = [
    "font_name", "font_size", "bold", "italic", "underline", "color",
    "alignment", "line_spacing", "space_before", "space_after",
    "first_line_indent", "left_indent",
]


class FormatOperation(BaseModel):
    """A single formatting change applied to a list of paragraphs."""
    paragraph_indices: list[int] = Field(description="Target paragraph indices")
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None
    color: Optional[str] = None
    alignment: Optional[str] = None
    line_spacing: Optional[float] = None
    space_before: Optional[float] = None
    space_after: Optional[float] = None
    first_line_indent: Optional[float] = None
    left_indent: Optional[float] = None


class FormatInstructionResult(BaseModel):
    """Complete structured output from the instruction-interpretation call."""
    operations: list[FormatOperation] = Field(default_factory=list)
    summary: str = Field(default="", description="Short Chinese summary of what was changed")


def operation_to_dict(op: FormatOperation) -> dict:
    """Convert a FormatOperation into the executor's dict form."""
    set_dict = {f: getattr(op, f) for f in PROPERTY_FIELDS if getattr(op, f) is not None}
    return {"paragraph_indices": op.paragraph_indices, "set": set_dict}


async def interpret_instruction(
    snapshot: dict,
    instruction: str,
) -> FormatInstructionResult:
    """Interpret an instruction into format operations via the LLM."""
    messages = build_format_instruction_prompt(snapshot, instruction)

    from langchain_openai import ChatOpenAI

    try:
        llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.1,
            max_tokens=4096,
        )
        structured = llm.with_structured_output(
            FormatInstructionResult,
            method="function_calling",
        )
        result: FormatInstructionResult = await structured.ainvoke(messages)
        return result

    except Exception as e1:
        logger.warning(f"Structured output failed: {type(e1).__name__}: {e1}")

        # Fallback: plain JSON mode
        try:
            llm2 = ChatOpenAI(
                model=settings.deepseek_model,
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                temperature=0.1,
                max_tokens=4096,
            )
            json_messages = list(messages)
            json_messages.append({
                "role": "user",
                "content": "\n\nIMPORTANT: Output ONLY valid JSON, no markdown, no code blocks.",
            })
            raw = await llm2.ainvoke(json_messages)
            raw_text = raw.content if hasattr(raw, "content") else str(raw)
            parsed = _parse_json_output(raw_text)

            ops = [FormatOperation(**o) for o in parsed.get("operations", [])]
            return FormatInstructionResult(
                operations=ops,
                summary=parsed.get("summary", ""),
            )

        except Exception as e2:
            logger.error(f"Both approaches failed: {e1} | {e2}")
            raise ValueError(f"无法理解该格式指令：{type(e2).__name__}: {str(e2)[:200]}") from e2
