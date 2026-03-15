"""Vision tool — Gemini Flash, image(s) -> structured text.

Deterministic interface: image bytes + optional context -> structured JSON dict.
Supports single image (backward compat) or up to 5 named images for comparative analysis.
Uses Google Gemini under the hood but from the system's perspective this is
an opaque tool: image in, text out.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_image_part(image_path: Path):
    """Load an image file and return a Gemini Part + its mime type."""
    from google.genai import types as genai_types

    data = image_path.read_bytes()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    return genai_types.Part.from_bytes(data=data, mime_type=mime)


async def vision(
    image_path: str | Path | None = None,
    images: list[dict] | None = None,
    context: dict | None = None,
) -> dict:
    """Send image(s) to Gemini Flash and return a structured analysis dict.

    Parameters
    ----------
    image_path : str or Path, optional
        Single image path (backward compat). Use this OR *images*, not both.
    images : list of dict, optional
        Up to 5 images for comparative analysis. Each dict has:
        - "name": reference name (e.g. "Channel1_trial5")
        - "path": absolute path to PNG/JPG
    context : dict, optional
        Signal context (signal_id, known_patterns, current_rule, TP/FP/FN/TN).
    """
    from google import genai
    import config

    client = genai.Client(api_key=config.GOOGLE_API_KEY)

    # Normalize inputs
    if image_path is not None and images is None:
        p = Path(image_path)
        images = [{"name": p.stem, "path": str(p)}]
    if images is None:
        return {"error": "No images provided. Pass image_path or images."}
    if len(images) > 5:
        return {"error": f"Maximum 5 images allowed, got {len(images)}."}

    # Validate all paths exist
    resolved = []
    for img in images:
        p = Path(img["path"])
        if not p.exists():
            return {"error": f"Image not found: {p}"}
        resolved.append({"name": img["name"], "path": p})

    multi = len(resolved) > 1

    # Build context text
    ctx_text = ""
    if context:
        ctx_text = "\n\nContext:\n" + json.dumps(context, indent=2)

    # Build prompt
    if multi:
        prompt = (
            "You are analyzing multiple images to compare and contrast them.\n"
            "Each image is labeled with a reference name.\n"
            "Return a JSON object with exactly these keys:\n"
            "  description        -- comparative summary of what you see across all images\n"
            "  similarities       -- what the signal have in common\n"
            "  differences        -- key differences between the signals\n"
            "  likely_patterns    -- object mapping each image name to its most likely pattern (or 'unknown')\n"
            "  rule_assessment    -- if a rule is in context, how well does it classify these signals?\n"
            "  suggested_feature_gap -- which feature might better discriminate these signals (or 'none')\n"
            + ctx_text
            + "\n\nReturn ONLY the JSON object, no markdown fences."
        )
    else:
        prompt = (
            "You are analyzing a signal plot to help identify patterns.\n"
            "Return a JSON object with exactly these keys:\n"
            "  description        -- one-sentence description of what you see\n"
            "  likely_pattern     -- most likely signal pattern name (or 'unknown')\n"
            "  rule_assessment    -- if a rule is in context, does it correctly classify this signal?\n"
            "  suggested_feature_gap -- which feature might better discriminate this signal (or 'none')\n"
            + ctx_text
            + "\n\nReturn ONLY the JSON object, no markdown fences."
        )

    # Build contents: interleave labeled images, then the prompt
    contents = []
    for img in resolved:
        contents.append(f"Image '{img['name']}':")
        contents.append(_load_image_part(img["path"]))
    contents.append(prompt)

    response = await client.aio.models.generate_content(
        model=config.VISION_MODEL,
        contents=contents,
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
    "name": "vision",
    "description": (
        "Send image(s) to Gemini Flash for analysis. "
        "Single image: returns description, likely_pattern, rule_assessment, suggested_feature_gap. "
        "Multiple images (up to 5): returns comparative analysis with similarities, differences, "
        "and per-image pattern classification. Use image_path for one image, or images for multiple."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Absolute path to a single PNG/JPG. Use this OR images, not both.",
            },
            "images": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Reference name for this image (e.g. 'Channel1_trial5')"},
                        "path": {"type": "string", "description": "Absolute path to the PNG/JPG"},
                    },
                    "required": ["name", "path"],
                },
                "description": "Up to 5 named images for comparative analysis. Each must have name and path.",
            },
            "context": {
                "type": "object",
                "description": (
                    "Optional context dict: signal_id, known_patterns, current_rule, "
                    "TP, FP, FN, TN counts."
                ),
            },
        },
        "required": [],
    },
}
