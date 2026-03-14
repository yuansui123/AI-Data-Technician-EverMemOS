"""Vision tool — Gemini Flash, single image -> structured text.

Deterministic interface: image bytes + optional context -> structured JSON dict.
Uses Google Gemini under the hood but from the system's perspective this is
an opaque tool: image in, text out.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path


async def vision(
    image_path: str | Path,
    context: dict | None = None,
) -> dict:
    """Send an image to Gemini Flash and return a structured analysis dict."""
    from google import genai
    from google.genai import types as genai_types
    import config

    client = genai.Client(api_key=config.GOOGLE_API_KEY)

    image_path = Path(image_path)
    if not image_path.exists():
        return {"error": f"Image not found: {image_path}"}

    image_data = base64.b64encode(image_path.read_bytes()).decode()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

    ctx_text = ""
    if context:
        ctx_text = "\n\nContext:\n" + json.dumps(context, indent=2)

    prompt = (
        "You are analyzing a neural signal plot to help identify patterns.\n"
        "Return a JSON object with exactly these keys:\n"
        "  description        -- one-sentence description of what you see\n"
        "  likely_pattern     -- most likely signal pattern name (or 'unknown')\n"
        "  rule_assessment    -- if a rule is in context, does it correctly classify this signal?\n"
        "  suggested_feature_gap -- which feature might better discriminate this signal (or 'none')\n"
        + ctx_text
        + "\n\nReturn ONLY the JSON object, no markdown fences."
    )

    response = await client.aio.models.generate_content(
        model=config.VISION_MODEL,
        contents=[
            genai_types.Part.from_bytes(data=base64.b64decode(image_data), mime_type=mime),
            prompt,
        ],
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_response": raw, "parse_error": "Could not decode JSON"}


# -- Anthropic tool schema --------------------------------------------------

SCHEMA: dict = {
    "name": "vision_analyze",
    "description": (
        "Send an image to Gemini Flash for analysis. "
        "Returns description, likely_pattern, rule_assessment, suggested_feature_gap."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Absolute path to the PNG/JPG."},
            "context": {
                "type": "object",
                "description": (
                    "Optional context dict: signal_id, known_patterns, current_rule, "
                    "TP, FP, FN, TN counts."
                ),
            },
        },
        "required": ["image_path"],
    },
}
