"""Tool: Build an HTML preview from a generated .docx file."""

import io

import mammoth


def build_preview_html(docx_buffer: bytes) -> str:
    """Convert a .docx buffer to a styled HTML preview.

    Uses mammoth to convert the .docx to clean HTML, then wraps it
    in an academic-modern styled template for in-browser preview.

    Args:
        docx_buffer: Raw .docx file bytes.

    Returns:
        Complete HTML document string for preview.
    """
    # Convert .docx to HTML using mammoth
    with io.BytesIO(docx_buffer) as f:
        result = mammoth.convert_to_html(f)

    body_html = result.value

    # Wrap in styled preview template
    preview_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body {{
        font-family: "Times New Roman", "Noto Serif SC", serif;
        font-size: 12pt;
        line-height: 1.6;
        max-width: 700px;
        margin: 2rem auto;
        padding: 0 1.5rem;
        color: #1a1a1a;
        background: #fff;
    }}
    h1 {{ font-size: 16pt; text-align: center; margin-bottom: 1rem; }}
    h2 {{ font-size: 14pt; margin-top: 1.5rem; }}
    h3 {{ font-size: 13pt; }}
    p {{ margin: 0.5rem 0; text-align: justify; }}
    blockquote {{
        margin: 1rem 2rem;
        padding-left: 1rem;
        border-left: 3px solid #ccc;
        color: #555;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 1rem 0;
    }}
    th, td {{
        border: 1px solid #ddd;
        padding: 8px;
        text-align: left;
    }}
    th {{ background: #f5f5f5; }}
    ul, ol {{ margin: 0.5rem 0; padding-left: 2rem; }}
    li {{ margin: 0.25rem 0; }}
    @media print {{
        body {{ margin: 0; padding: 0; }}
    }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

    return preview_html


def get_preview_warnings(docx_buffer: bytes) -> list[str]:
    """Get any warnings or messages from the mammoth conversion.

    Args:
        docx_buffer: Raw .docx file bytes.

    Returns:
        List of warning messages.
    """
    with io.BytesIO(docx_buffer) as f:
        result = mammoth.convert_to_html(f)

    return result.messages
