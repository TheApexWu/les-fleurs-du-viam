"""Planner (sentiment -> composition) and critic (photo -> sentiment guess + one edit).

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
INVENTORY = Path(__file__).parent / "inventory.json"


def load_inventory() -> list[dict]:
    """Tray contents, filled in on the day: [{"slot": 0, "flower": "white chrysanthemum", "height_mm": 300}, ...]"""
    return json.loads(INVENTORY.read_text()) if INVENTORY.exists() else []


def _ask(content, max_tokens=600) -> dict:
    import anthropic
    msg = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=max_tokens,
                                                messages=[{"role": "user", "content": content}])
    text = msg.content[0].text
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def plan(sentiment: str, inventory: list[dict]) -> dict:
    prompt = (
        "You compose small ikebana-style arrangements for a robot arm. Express the sentiment "
        f"'{sentiment}' using only stems from this tray: {json.dumps(inventory)}.\n"
        "Return JSON: {\"why\": str, \"stems\": [{\"role\": \"shin|soe|hikae|filler\", \"slot\": int, "
        "\"tilt\": degrees from vertical 0-75, \"azimuth\": 0-360, \"x\": mm -30..30, \"y\": mm -30..30}]} "
        "with 3 to 5 stems. Composition (tilt, spacing, negative space) should carry the meaning, not just flower choice."
    )
    try:
        out = _ask([{"type": "text", "text": prompt}])
        assert isinstance(out.get("stems"), list) and out["stems"]
        return out
    except Exception as e:  # noqa: BLE001 - any API or parse failure falls back to the classic form
        print("planner fallback:", type(e).__name__)
        slots = [s["slot"] for s in inventory[:3]] or [0, 1, 2]
        return {"why": "fallback: Sogetsu basic upright", "stems": [
            {"role": r, "slot": s, "tilt": t, "azimuth": a, "x": x, "y": y}
            for (r, t, a, x, y), s in zip([("shin", 12, 200, -8, 6), ("soe", 45, 225, -10, -8),
                                           ("hikae", 75, 315, 10, -10)], slots)]}


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
