"""Blind critic: photo -> guess of the feeling + one suggested edit.

The critic never sees the target sentiment: it picks from a fixed list, so it can't just agree.
Both calls return JSON validated before the robot acts on it, and both fall back to something
safe when the API is slow or garbled, so the live demo never depends on them.
"""
import base64
import json
import os
from pathlib import Path

SENTIMENTS = ["gratitude", "apology", "love", "grief", "celebration", "calm", "longing", "hope"]
MODEL = os.environ.get("FLOWERS_MODEL", "claude-sonnet-5")


def critique(photo_path: str) -> dict:
    img = base64.standard_b64encode(Path(photo_path).read_bytes()).decode()
    prompt = (
        f"This is a photo of a small flower arrangement. Which ONE of these sentiments does it express "
        f"most: {', '.join(SENTIMENTS)}? Judge the composition (angles, spacing, balance, negative space) "
        "as well as the flowers. Return JSON: {\"guess\": one of the list, \"confidence\": 0-1, "
        "\"reason\": short, \"edit\": {\"slot\": int or null, \"d_tilt\": degrees, \"d_azimuth\": degrees, "
        "\"remove\": bool}} where edit is the single change that would most strengthen what the arrangement "
        "is trying to say."
    )
    try:
        return _ask([{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}},
                     {"type": "text", "text": prompt}])
    except Exception as e:  # noqa: BLE001
        return {"guess": None, "error": type(e).__name__}
