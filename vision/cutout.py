"""Cut a single flower (stem and bloom) off a plain white table, and find its bloom.

Flower = anything that is not table: the table is bright and unsaturated, with soft shadows.
Bloom = the flower minus foliage (green stems and leaves). White carnations are found as the
non-green part of the flower near the stem's end, so they don't depend on colour.
"""
import cv2
import numpy as np

TEXTURE = 18.0


def flower_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    table = cv2.GaussianBlur(v, (0, 0), 25)  # local table brightness, follows shadows
    not_table = (s > 45) | (v < table.astype(np.int16) - 28)
    m = cv2.morphologyEx(not_table.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        return np.zeros_like(m)
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # the flower; shadow streaks are separate blobs
    flower = ((lab == biggest) * 255).astype(np.uint8)
    # white petals match the table's colour but are ruffled: add strongly textured pixels right next to the flower
    edges = cv2.blur(np.abs(cv2.Laplacian(cv2.GaussianBlur(v, (3, 3), 0), cv2.CV_32F, ksize=3)), (11, 11))
    near = cv2.dilate(flower, np.ones((61, 61), np.uint8)) > 0
    ruffle = ((edges > TEXTURE) & near & (v > 150)).astype(np.uint8) * 255
    ruffle = cv2.morphologyEx(ruffle, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return cv2.bitwise_or(flower, ruffle)


def bloom_mask(bgr, fmask):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    foliage = (h >= 30) & (h <= 95) & (s > 35)
    pale = (s <= 45) & (v > 140)  # white petals inside the flower mask
    bloom = ((fmask > 0) & (~foliage | pale)).astype(np.uint8) * 255
    bloom = cv2.morphologyEx(bloom, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    bloom = cv2.morphologyEx(bloom, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bloom)
    out = np.zeros_like(bloom)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] > 0.004 * bloom.size:
            out[lab == i] = 255
    return out
