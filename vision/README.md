# Flower vision

Finds flowers on the white table and names them by **variety** (rose, carnation, lily: a small YOLOv8n
model) and **colour** (read from the bloom's pixels, limited to the colours we stock per variety).

```
pip install ultralytics
python vision/flowers_detect.py photo.jpg out.jpg     # one image, writes boxes to out.jpg
python vision/flowers_detect.py --cam out.jpg         # one frame from the wrist camera (needs .env)
```

In code (for the bouquet backend's `/api/inventory`):

```python
from vision.flowers_detect import detect, inventory
dets = detect(bgr_image)          # [{variety, colour, confidence, bbox: (x1, y1, x2, y2)}]
counts = inventory(dets)          # Counter({"red rose": 1, "white carnation": 2, ...})
```

Stocked colours (`STOCK` in `flowers_detect.py`): rose yellow/red/pink, carnation white/red-white,
lily orange/yellow. A new flower type needs photos and a retrain; a new colour of an existing type
needs one line in `STOCK`.

## How the model was made
- 13 single-flower phone photos on the white table (`data/single/`, labelled by filename) plus rose
  crops from one group photo and the wrist camera. Two white carnation heads are hand-boxed in
  `data/single/boxes.json`; white petals on a white table defeat the automatic cut-out.
- `synth.py` cuts each flower out and pastes 1-5 at random angles and sizes onto empty-table
  backgrounds: 320 training images with exact labels. `train` is 15 epochs, strong colour/scale/flip
  augmentation. Three classes only, to limit memorising individual flowers.
- Honest test: IMG_9607, a group photo never used for training. See the commit message for the score.

## Known limits
- White carnations on a white table are the weakest; a darker surface under them helps more than more data.
- Boxes merge when blooms touch; lay flowers a few cm apart.
- Phone photos, not wrist-camera frames, trained this. Check on a live `--cam` frame before relying on it.
