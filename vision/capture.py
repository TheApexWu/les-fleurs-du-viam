"""Save wrist-camera frames for training, named by the flower on the board. Read-only on the robot.

  python vision/capture.py rose_yellow      press Enter for each shot; Ctrl-C when done
Files go to vision/data/single/<name>_cam<N>.jpg, the same filename-is-label scheme as the phone photos.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from flowers import connect  # noqa: E402
from viam.components.camera import Camera  # noqa: E402

import config as K  # noqa: E402

OUT = Path(__file__).parent / "data" / "single"


async def main(name):
    robot = await connect()
    cam = Camera.from_robot(robot, K.CAMERA)
    n = len(list(OUT.glob(f"{name}_cam*.jpg")))
    try:
        while True:
            await asyncio.to_thread(input, f"{name}: place it near the board centre, Enter to shoot (Ctrl-C to stop) ")
            imgs, _ = await cam.get_images(filter_source_names=["color"])
            n += 1
            path = OUT / f"{name}_cam{n}.jpg"
            path.write_bytes(imgs[0].data)
            print("saved", path.name)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        await robot.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
