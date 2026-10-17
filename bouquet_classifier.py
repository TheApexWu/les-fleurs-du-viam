"""Same-frame adapter for the classifier merged from the vision branch."""
from __future__ import annotations


def classify_frame(image, confidence=0.3):
    """Return bloom boxes, variety and color; never derive a robot grasp from a box."""
    try:
        import numpy as np
        from vision.flowers_detect import detect
    except ImportError as exc:
        raise RuntimeError("Flower classifier dependencies are missing. Run: python -m pip install -r requirements.txt") from exc
    bgr = np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
    return detect(bgr, conf=confidence)


def classify_detections(image, detections, confidence=0.3):
    """Adapt same-frame Viam variety boxes; color comes only from bloom pixels."""
    import math
    import numpy as np
    from bouquet_core import FLOWER_STOCK
    from vision.flowers_detect import colour_of

    bgr = np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
    flowers = []
    for detection in detections:
        variety = detection.class_name.strip().lower()
        score = float(detection.confidence)
        if variety not in FLOWER_STOCK or not math.isfinite(score) or not confidence <= score <= 1:
            continue
        box = [int(getattr(detection, key)) for key in ("x_min", "y_min", "x_max", "y_max")]
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
            continue
        flowers.append({"variety": variety, "colour": colour_of(bgr[y0:y1, x0:x1], variety),
                        "confidence": score, "bbox": box})
    return flowers
