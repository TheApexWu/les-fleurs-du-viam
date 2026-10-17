"""Detect flowers (variety by the trained model, colour from the bloom's pixels).

  python vision/flowers_detect.py photo.jpg [out.jpg]     one image
  python vision/flowers_detect.py --cam [out.jpg]         one frame from the wrist camera

Returns [{variety, colour, confidence, bbox}] and an inventory count by "colour variety",
the shape S's bouquet backend needs for /api/inventory.
"""
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

WEIGHTS = Path(__file__).parent / "weights" / "flowers.pt"
_model = None


# What we actually have in stock: colour is chosen among these, so a pale lily can't become "white".
STOCK = {"rose": ("yellow", "red", "pink"), "carnation": ("white", "red-white"), "lily": ("orange", "yellow")}


def colour_of(bgr_crop, variety):
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    keep = ~((h >= 35) & (h <= 95) & (s > 35))  # drop leaves and stem
    h, s, v = h[keep], s[keep], v[keep]
    if len(h) == 0:
        return "unknown"
    frac = {
        "red": np.mean(((h <= 7) | (h >= 168)) & (s > 90)),
        "pink": np.mean((h >= 135) & (h < 168) & (s > 40)),
        "orange": np.mean((h >= 8) & (h <= 19) & (s > 90)),
        "yellow": np.mean((h >= 20) & (h <= 34) & (s > 40)),
    }
    frac["red-white"] = frac["red"] if frac["red"] > 0.03 else 0.0  # carnation stripes: some red among white
    frac["white"] = 0.05 if frac["red"] <= 0.03 else 0.0
    allowed = STOCK.get(variety, tuple(frac))
    return max(allowed, key=lambda c: frac.get(c, 0.0))


def detect(bgr, conf=0.3):
    global _model
    _model = _model or YOLO(str(WEIGHTS))
    r = _model.predict(bgr, conf=conf, iou=0.4, agnostic_nms=True, verbose=False)[0]
    out = []
    for b in r.boxes:
        x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
        variety = r.names[int(b.cls)]
        out.append({"variety": variety, "colour": colour_of(bgr[y1:y2, x1:x2], variety),
                    "confidence": round(float(b.conf), 2), "bbox": (x1, y1, x2, y2)})
    return sorted(out, key=lambda d: d["bbox"][0])


def inventory(dets):
    return Counter(f"{d['colour']} {d['variety']}" for d in dets)


def draw(bgr, dets):
    for d in dets:
        x1, y1, x2, y2 = d["bbox"]
        cv2.rectangle(bgr, (x1, y1), (x2, y2), (0, 0, 255), 3)
        cv2.putText(bgr, f"{d['colour']} {d['variety']} {d['confidence']:.2f}", (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return bgr


def wrist_frame():
    import asyncio
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from flowers import connect
    from viam.components.camera import Camera
    import config as K

    async def grab():
        r = await connect()
        try:
            imgs, _ = await Camera.from_robot(r, K.CAMERA).get_images(filter_source_names=["color"])
            return cv2.imdecode(np.frombuffer(imgs[0].data, np.uint8), cv2.IMREAD_COLOR)
        finally:
            await r.close()
    return asyncio.run(grab())


if __name__ == "__main__":
    img = wrist_frame() if sys.argv[1] == "--cam" else cv2.imread(sys.argv[1])
    dets = detect(img)
    for d in dets:
        print(f"{d['colour']:9s} {d['variety']:9s} {d['confidence']:.2f} {d['bbox']}")
    print("inventory:", dict(inventory(dets)))
    if len(sys.argv) > 2:
        cv2.imwrite(sys.argv[2], draw(img, dets))
