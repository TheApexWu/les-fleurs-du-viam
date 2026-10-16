"""Re-export armfarm12's config from the Viam app into armfarm12-config.json (redacts the arm IP and camera serial)."""
import asyncio
import json
import os
from pathlib import Path

from viam.app.viam_client import ViamClient
from viam.rpc.dial import DialOptions

LOCATION, ROBOT, PART = "310sld03v2", "armfarm12", "armfarm12-main"


async def main():
    vc = await ViamClient.create_from_dial_options(DialOptions.with_api_key(
        api_key=os.environ["VIAM_API_KEY"], api_key_id=os.environ["VIAM_API_KEY_ID"]))
    try:
        robot = next(r for r in await vc.app_client.list_robots(location_id=LOCATION) if r.name == ROBOT)
        part = next(p for p in await vc.app_client.get_robot_parts(robot.id) if p.name == PART)
        cfg = part.robot_config
        for frag in cfg.get("fragments", []):
            v = frag.get("variables", {})
            for k in ("arm-ip-address", "cam-serial-number"):
                if k in v:
                    v[k] = "<redacted>"
        out = Path(__file__).parent / "armfarm12-config.json"
        out.write_text(json.dumps(cfg, indent=2, default=str) + "\n")
        print("wrote", out)
    finally:
        vc.close()


if __name__ == "__main__":
    asyncio.run(main())
