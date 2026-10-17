"""Bouquet UI and calibration commands. Default server mode is read-only.

  python bouquet.py serve                    camera + plan preview; no motion
  python bouquet.py serve --demo             in-memory bouquet simulation
  python bouquet.py serve --staged-demo staged_demo.json --allow-motion
  python bouquet.py scan                     one read-only live inventory scan
  python bouquet.py init                     create an unverified calibration draft
  python bouquet.py capture-scan             save current scan frames; moves nothing

Only `serve --allow-motion` can execute transfers, after the selected setup is verified.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from aiohttp import web

from bouquet_orders import OrderController, OrderRejected
from bouquet_vision import (DemoInventoryBackend, ViamInventoryBackend, default_calibration,
                            load_calibration, utc_now)
import config as K

ROOT = Path(__file__).parent
CONTROLLER = web.AppKey("bouquet_controller", OrderController)
BACKEND = web.AppKey("bouquet_backend", object)
logger = logging.getLogger(__name__)


def configure_logging():
    log_path = ROOT / "logs" / "bouquet.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), RotatingFileHandler(
            log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")],
    )
    # Browser polling is frequent; keep inventory and order events prominent.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logger.info("Logging to %s", log_path)


@web.middleware
async def api_errors(request, handler):
    try:
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                return web.json_response({"error": "Cross-origin control requests are refused."}, status=403)
            if request.can_read_body and request.content_type != "application/json":
                return web.json_response({"error": "Send application/json."}, status=415)
        response = await handler(request)
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    except OrderRejected as exc:
        logger.warning("%s %s rejected status=%s details=%s", request.method, request.path, exc.status, exc.payload)
        return web.json_response(exc.payload, status=exc.status)
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("%s %s invalid request: %s", request.method, request.path, exc)
        return web.json_response({"error": str(exc)}, status=400)
    except web.HTTPException:
        raise
    except Exception as exc:
        logger.exception("%s %s failed", request.method, request.path)
        return web.json_response({"error": f"{type(exc).__name__}: {str(exc)[:220]}"}, status=503)


async def build_app(*, backend=None, allow_motion=False, calibration_path=K.BOUQUET_CALIBRATION):
    backend = backend or ViamInventoryBackend(calibration_path, allow_motion=allow_motion)
    controller = OrderController(backend, allow_motion=allow_motion)
    app = web.Application(middlewares=[api_errors], client_max_size=16 * 1024)
    app[CONTROLLER], app[BACKEND] = controller, backend

    async def index(_):
        return web.FileResponse(ROOT / "bouquet_ui" / "index.html")

    async def inventory(_):
        snapshot = deepcopy(backend.snapshot)
        if snapshot is None:
            snapshot = await controller.scan()
        elif snapshot.get("mode") == "live":
            captured = datetime.fromisoformat(snapshot["detected_at"])
            if (datetime.now(timezone.utc) - captured).total_seconds() > 10:
                snapshot["ready"] = False
                snapshot.setdefault("blockers", []).append("Inventory is stale; scan the table again.")
        return web.json_response(snapshot)

    async def scan(_):
        return web.json_response(await controller.scan())

    async def plan(request):
        result = await controller.plan(await request.json())
        if not allow_motion and (getattr(backend, "snapshot", None) or {}).get("mode") != "demo":
            result["ready"] = False
            result.setdefault("blockers", []).append("Read-only session: physical bouquet execution is disabled.")
        return web.json_response(result)

    async def start(request):
        return web.json_response(await controller.start(await request.json()), status=202)

    async def current(_):
        return web.json_response(controller.current() or {"status": "idle", "completed": 0, "steps": []})

    async def stop(_):
        order = await controller.stop()
        return web.json_response(order or {"status": "stopped", "completed": 0, "steps": []})

    async def frame(_):
        if not backend.jpeg:
            raise web.HTTPServiceUnavailable(text="No camera frame has been scanned yet.")
        return web.Response(body=backend.jpeg, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def calibration(_):
        result = load_calibration(calibration_path)
        return web.json_response({"calibration": result, "execution_enabled": allow_motion,
                                  "path": str(Path(calibration_path).name)})

    async def cleanup(_):
        await controller.close()

    app.add_routes([
        web.get("/", index), web.get("/api/inventory", inventory), web.post("/api/scan", scan),
        web.post("/api/plan", plan), web.post("/api/orders", start),
        web.get("/api/orders/current", current), web.post("/api/stop", stop),
        web.get("/api/frame.jpg", frame), web.get("/api/calibration", calibration),
    ])
    app.router.add_static("/static/", ROOT / "bouquet_ui", show_index=False)
    app.on_cleanup.append(cleanup)
    return app


def save_calibration(path, calibration):
    """Atomically save an operator's calibration without ever making it verified."""
    calibration.setdefault("reference", {})["verified"] = False
    path = Path(path)
    # A local code edit/calibration must be explicitly rechecked before execution.
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".vision-calibration-", delete=False) as stream:
        json.dump(calibration, stream, indent=2, allow_nan=False)
        stream.write("\n")
        temp_path = Path(stream.name)
    temp_path.replace(path)


async def calibration_command(args):
    path = Path(args.calibration)
    if args.command == "prepare-commissioning":
        from bouquet_commissioning import prepare_commissioning
        output = Path(args.output)
        if output.resolve() == path.resolve():
            raise ValueError("Keep commissioning separate from the original calibration file.")
        calibration = prepare_commissioning(load_calibration(path))
        save_calibration(output, calibration)
        print(f"Saved {output}. Preview bounds only; verified calibration and removal of the preview correction are still required for motion.")
        return
    if args.command == "init":
        if path.exists():
            raise ValueError(f"{path.name} already exists; preserved it. Edit it or use a different --calibration path.")
        calibration = default_calibration()
    else:
        calibration = load_calibration(path)

    if args.command in ("init", "copy-reference"):
        taught = K.taught()
        required = ("pickup_approach", "pretend_grasp", "lift")
        if not all(key in taught for key in required):
            raise ValueError("Capture the working three pickup poses in taught_poses.json first.")
        calibration.setdefault("reference", {})["pickup_poses"] = {key: deepcopy(taught[key]) for key in required}
    elif args.command == "capture-scan":
        backend = ViamInventoryBackend(path)
        try:
            calibration["scan_pose"] = await backend.current_pose()
            calibration["scan_camera_pose"] = await backend.current_pose(calibration.get("camera", K.CAMERA))
            frame, _ = await backend.capture_frame()
            calibration["image_size"] = [frame.width, frame.height]
            calibration["scan_captured_at"] = utc_now()
        finally:
            await backend.close()
    elif args.command == "set-reference":
        calibration.setdefault("reference", {}).update(pixel=args.pixel,
                                                         axis_pixels=[args.axis[:2], args.axis[2:]])
    elif args.command == "set-table":
        calibration["table_plane_z_mm"] = args.z
    elif args.command == "set-workspace":
        if any(lo >= hi for lo, hi in (args.x, args.y, args.z)):
            raise ValueError("Each workspace minimum must be less than its maximum.")
        calibration["workspace_bounds"] = {"x": args.x, "y": args.y, "z": args.z}
    save_calibration(path, calibration)
    print(f"Saved {path.name}. Calibration is UNVERIFIED; no arm or gripper commands were sent.")


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--calibration", default=str(K.BOUQUET_CALIBRATION))
    sub = result.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Open the bouquet UI; read-only by default")
    serve.add_argument("--port", type=int, default=8770)
    serve.add_argument("--staged-demo", metavar="PROFILE",
                       help="Use three taught, operator-labeled slots; motion still requires --allow-motion and verified setup")
    serve.add_argument("--commission-one", action="store_true",
                       help="Limit a verified supervised trial to one flower; requires --allow-motion and does not bypass calibration")
    modes = serve.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="In-memory simulation; never connects to hardware")
    modes.add_argument("--allow-motion", action="store_true", help="Enable physical transfers after measured calibration is verified")
    sub.add_parser("scan", help="Read one inventory snapshot; never moves hardware")
    sub.add_parser("init", help="Create an unverified table calibration using the working pickup template")
    sub.add_parser("copy-reference", help="Copy only the three known pickup poses into the calibration draft")
    sub.add_parser("capture-scan", help="Read the current gripper/camera world poses; moves nothing")
    commissioning = sub.add_parser("prepare-commissioning", help="Derive a separate bounded one-flower trial file; moves nothing")
    commissioning.add_argument("--output", default=str(ROOT / "commissioning_inventory.json"))
    reference = sub.add_parser("set-reference", help="Set known grasp pixel and directed stem axis in the scan image")
    reference.add_argument("--pixel", type=float, nargs=2, required=True, metavar=("U", "V"))
    reference.add_argument("--axis", type=float, nargs=4, required=True, metavar=("BASE_U", "BASE_V", "BLOOM_U", "BLOOM_V"))
    table = sub.add_parser("set-table", help="Set the measured world Z of stems lying on the pickup surface")
    table.add_argument("--z", type=float, required=True)
    bounds = sub.add_parser("set-workspace", help="Set the measured pickup workspace limits in world millimeters")
    for axis in ("x", "y", "z"):
        bounds.add_argument(f"--{axis}", type=float, nargs=2, required=True)
    return result


def main():
    args = parser().parse_args()
    configure_logging()
    if args.command == "serve":
        if args.staged_demo and (args.demo or args.commission_one):
            raise SystemExit("Staged physical slots cannot be combined with --demo or --commission-one.")
        if args.commission_one and not args.allow_motion:
            raise SystemExit("--commission-one requires --allow-motion and the commissioning calibration file.")
        if args.commission_one:
            from bouquet_commissioning import check_commissioning
            check_commissioning(load_calibration(args.calibration))
            K.FAST_DEG_S, K.SLOW_DEG_S = min(K.FAST_DEG_S, 6), min(K.SLOW_DEG_S, 6)
            K.ACCEL_DEG_S2 = min(K.ACCEL_DEG_S2, 30)
        if args.staged_demo:
            from bouquet_staged import StagedInventoryBackend
            args.calibration = args.staged_demo
            backend = StagedInventoryBackend(args.staged_demo, allow_motion=args.allow_motion)
        else:
            backend = DemoInventoryBackend() if args.demo else ViamInventoryBackend(
                args.calibration, allow_motion=args.allow_motion, commission_one=args.commission_one)
        mode = "SUPERVISED ONE-FLOWER LIMIT; calibration gates apply" if args.commission_one else "demo" if args.demo else "motion enabled; calibration gates apply" if args.allow_motion else "read-only"
        if args.staged_demo:
            mode = "STAGED DEMO; physical arm enabled, verified fixed slots required" if args.allow_motion else "STAGED DEMO; read-only"
        logger.info("Server mode=%s calibration=%s plan_checks=%s", mode, args.calibration, K.PLAN_CHECK)
        print("Bouquet preview: http://127.0.0.1:%s (%s)" % (args.port, mode))
        web.run_app(build_app(backend=backend, allow_motion=args.allow_motion, calibration_path=args.calibration),
                    host="127.0.0.1", port=args.port)
    elif args.command == "scan":
        async def scan_once():
            backend = ViamInventoryBackend(args.calibration)
            try:
                print(json.dumps(await backend.scan(), indent=2))
            finally:
                await backend.close()
        asyncio.run(scan_once())
    else:
        asyncio.run(calibration_command(args))


if __name__ == "__main__":
    main()
