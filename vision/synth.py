"""Build a YOLO dataset by pasting real flower cut-outs onto empty table backgrounds.

Labels are exact because we know where each bloom was pasted. Classes are variety_colour.
"""
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from cutout import bloom_mask, flower_mask  # noqa: E402

DATA = Path(__file__).parent / "data"
CLASSES = ["rose", "carnation", "lily"]  # variety only; colour is read from pixels afterwards, so it can't be memorised


def sprites():
    """(rgb, alpha, bloom_alpha, class) for every cut-out. Hand-labelled heads (white on white, which no
    colour or texture rule finds reliably) come from single/boxes.json."""
    out = []
    hand = json.loads((DATA / "single" / "boxes.json").read_text()) if (DATA / "single" / "boxes.json").exists() else {}
    for f in sorted((DATA / "single").glob("*.jpg")):
        cls = f.stem.rsplit("_", 1)[0]
        img = cv2.imread(str(f))
        fm = flower_mask(img)
        bm = bloom_mask(img, fm)
        cs, _ = cv2.findContours(bm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cls.startswith("carnation") and cs:
            cs = [max(cs, key=cv2.contourArea)]  # one head per carnation; tape or debris is not a bloom
        hulls = np.zeros_like(bm)
        if f.stem in hand:
            x1, y1, x2, y2 = hand[f.stem]
            cv2.ellipse(hulls, ((x1 + x2) // 2, (y1 + y2) // 2), ((x2 - x1) // 2, (y2 - y1) // 2), 0, 0, 360, 255, -1)
        else:
            cv2.drawContours(hulls, [cv2.convexHull(c) for c in cs], -1, 255, -1)  # solid blooms, no petal holes
        alpha = cv2.morphologyEx(fm | hulls, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        x, y, w, h = cv2.boundingRect(alpha)
        out.append((img[y:y + h, x:x + w], alpha[y:y + h, x:x + w], hulls[y:y + h, x:x + w], cls))
    # roses: bloom crops from the group photo and the wrist camera (box = x1, y1, x2, y2)
    for src, boxes in {"group_9599.jpg": [((0, 190, 200, 380), "rose_yellow"), ((215, 222, 430, 372), "rose_yellow"),
                                          ((402, 150, 668, 355), "rose_red"), ((0, 395, 185, 620), "rose_pink")],
                       "rose_red_wristcam.jpg": [((628, 180, 792, 335), "rose_red")]}.items():
        img = cv2.imread(str(DATA / src))
        if img is None:
            continue
        for (x1, y1, x2, y2), cls in boxes:
            crop = img[y1:y2, x1:x2]
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            petals = ((hsv[..., 1] > 60) & ((hsv[..., 0] < 30) | (hsv[..., 0] > 135))).astype(np.uint8) * 255
            petals = cv2.morphologyEx(petals, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            n, lab, stats, _ = cv2.connectedComponentsWithStats(petals)
            if n < 2:
                continue
            big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # the bloom, not a neighbour's edge
            a = cv2.morphologyEx(((lab == big) * 255).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
            x, y, w, h = cv2.boundingRect(a)
            out.append((crop[y:y + h, x:x + w], a[y:y + h, x:x + w], a[y:y + h, x:x + w].copy(), cls))
    return out


def background(rng, size=640):
    """Empty table: a single-flower photo with its flower painted out, or (30%) a real wrist-camera frame of
    the board and hazard tape, so tape and glare are learned as background. Randomly cropped and tinted."""
    negatives = sorted((DATA / "negatives").glob("*.jpg"))
    if negatives and rng.random() < 0.3:
        img = cv2.imread(str(rng.choice(negatives)))
        h, w = img.shape[:2]
        side = rng.randint(min(h, w) // 2, min(h, w))
        x0, y0 = rng.randint(0, w - side), rng.randint(0, h - side)
        crop = cv2.resize(img[y0:y0 + side, x0:x0 + side], (size, size))
        return np.clip(crop.astype(np.float32) * rng.uniform(0.85, 1.15), 0, 255).astype(np.uint8)
    f = rng.choice(sorted(p for p in (DATA / "single").glob("*.jpg") if "_cam" not in p.stem))
    img = cv2.imread(str(f))
    fm = flower_mask(img)
    bm = bloom_mask(img, fm)
    cs, _ = cv2.findContours(bm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(fm, [cv2.convexHull(c) for c in cs], -1, 255, -1)  # white petals too, or they ghost
    m = cv2.dilate(fm, np.ones((61, 61), np.uint8))
    clean = cv2.inpaint(cv2.resize(img, None, fx=0.5, fy=0.5), cv2.resize(m, None, fx=0.5, fy=0.5), 9, cv2.INPAINT_TELEA)
    clean = cv2.resize(clean, (size, size))
    return np.clip(clean.astype(np.float32) * rng.uniform(0.85, 1.1), 0, 255).astype(np.uint8)


def paste(bg, sprite, rng, scale):
    rgb, a, b, _ = sprite
    rgb, a, b = (cv2.resize(t, None, fx=scale, fy=scale) for t in (rgb, a, b))
    ang = rng.uniform(0, 360)
    h, w = a.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    rgb, a, b = (cv2.warpAffine(t, M, (nw, nh)) for t in (rgb, a, b))
    H, W = bg.shape[:2]
    if nw >= W or nh >= H:
        return None
    x0, y0 = rng.randint(0, W - nw), rng.randint(0, H - nh)
    alpha = (cv2.GaussianBlur(a, (5, 5), 0).astype(np.float32) / 255)[..., None]
    region = bg[y0:y0 + nh, x0:x0 + nw]
    bg[y0:y0 + nh, x0:x0 + nw] = (alpha * rgb + (1 - alpha) * region).astype(np.uint8)
    boxes = []
    cs, _ = cv2.findContours((b > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cs:
        if cv2.contourArea(c) > 150:
            x, y, bw, bh = cv2.boundingRect(c)
            boxes.append((x0 + x, y0 + y, x0 + x + bw, y0 + y + bh))
    return boxes


def build(n_train=320, n_val=60, seed=0, out=DATA / "synth"):
    rng = random.Random(seed)
    sps = sprites()
    counts = {}
    for split, n in (("train", n_train), ("val", n_val)):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            bg = background(rng)
            labels = []
            for _ in range(rng.randint(1, 5)):
                sp = rng.choice(sps)
                scale = rng.uniform(0.35, 0.9) * (640 / max(sp[1].shape)) * (0.55 if sp[3].startswith("rose") else 1.0) \
                    if sp[3].startswith(("lily", "carnation")) else rng.uniform(0.5, 1.1)
                boxes = paste(bg, sp, rng, scale)
                for x1, y1, x2, y2 in boxes or []:
                    c = CLASSES.index(sp[3].split("_")[0])
                    counts[sp[3]] = counts.get(sp[3], 0) + 1
                    labels.append(f"{c} {(x1 + x2) / 1280:.5f} {(y1 + y2) / 1280:.5f} {(x2 - x1) / 640:.5f} {(y2 - y1) / 640:.5f}")
            cv2.imwrite(str(out / "images" / split / f"{i:04d}.jpg"), bg)
            (out / "labels" / split / f"{i:04d}.txt").write_text("\n".join(labels))
    (out / "data.yaml").write_text(f"path: {out}\ntrain: images/train\nval: images/val\nnames: {json.dumps(dict(enumerate(CLASSES)))}\n")
    print("sprites", len(sps), "| labelled blooms", counts)


if __name__ == "__main__":
    build()
