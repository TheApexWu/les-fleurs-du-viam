"""Integration boundaries exercised with in-memory cameras and fake robot methods."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from viam.media.video import CameraMimeType, NamedImage
from viam.proto.common import Pose, ResponseMetadata, WorldState
from viam.proto.component.camera import GetPropertiesResponse, IntrinsicParameters
from viam.proto.service.vision import Detection

import bouquet
from bouquet_vision import (DemoInventoryBackend, DetectionTracker, ViamInventoryBackend,
                            camera_geometry_for_scan, default_calibration, normalize_table_candidate, pose_matches, utc_now)
from flowers import FlowerBot
import config as K


def pose(x=200., y=100., z=100.):
    return {"x": x, "y": y, "z": z, "o_x": 0., "o_y": 0., "o_z": -1., "theta": 0.}


class FlowerFlowTests(unittest.IsolatedAsyncioTestCase):
    def bot(self):
        bot = object.__new__(FlowerBot)
        for name in ("setup", "speed", "open_gripper", "move", "wait_gripper_idle"):
            setattr(bot, name, AsyncMock())
        bot.grip = AsyncMock(return_value=True)
        bot.gripper_width = AsyncMock(return_value=45)
        bot.gripper = type("FakeGripper", (), {"is_holding_something": AsyncMock(
            return_value=type("Holding", (), {"is_holding_something": True, "meta": {}})())})()
        return bot

    async def test_dynamic_pickup_keeps_original_vase_poses_and_gripper_order(self):
        original = {key: pose(x=100. + i * 20) for i, key in enumerate(
            ("pickup_approach", "pretend_grasp", "lift", "vase_approach", "pretend_release"))}
        override = {key: pose(x=300. + i * 20) for i, key in enumerate(
            ("pickup_approach", "pretend_grasp", "lift"))}
        bot, stages = self.bot(), []

        async def on_stage(stage):
            stages.append(stage)

        with patch.object(K, "taught", return_value=original), redirect_stdout(io.StringIO()):
            await bot.pick_and_drop(override, on_stage=on_stage)
        actual = [call.args[0] for call in bot.move.await_args_list]
        self.assertEqual(actual[0].x, override["pickup_approach"]["x"])
        self.assertEqual(actual[1].x, override["pretend_grasp"]["x"])
        self.assertEqual(actual[3].x, original["vase_approach"]["x"])
        self.assertEqual(actual[4].x, original["pretend_release"]["x"])
        self.assertLess(stages.index("grasped"), stages.index("released"))
        self.assertEqual(stages[-1], "returned")
        self.assertEqual(bot.grip.await_count, 1)
        self.assertEqual(bot.open_gripper.await_count, 2)

    async def test_invalid_pickup_rejected_before_setup(self):
        bot = self.bot()
        with self.assertRaises(ValueError):
            await bot.pick_and_drop({"pretend_grasp": pose()})
        bot.setup.assert_not_awaited()

    async def test_false_motion_result_is_a_failure(self):
        bot = object.__new__(FlowerBot)
        bot.obstacles = lambda: WorldState()
        bot.motion = type("FakeMotion", (), {"move": AsyncMock(return_value=False)})()
        with patch.object(K, "PLAN_CHECK", False), self.assertRaises(RuntimeError):
            await bot.move(Pose(**pose()))


class ReadOnlyVisionTests(unittest.IsolatedAsyncioTestCase):
    def preview_calibration(self):
        calibration = default_calibration()
        intrinsics = {"fx": 90., "fy": 90., "cx": 64., "cy": 36., "width": 128, "height": 72}
        calibration["projection_preview"] = {"reported_camera_pose": pose(),
            "camera_pose_world": pose(z=95.), "intrinsics": intrinsics}
        return calibration, intrinsics

    def test_preview_corrects_projection_and_always_blocks_execution(self):
        calibration, intrinsics = self.preview_calibration()
        calibration["reference"]["verified"] = True
        geometry, blockers = camera_geometry_for_scan(pose(), intrinsics, calibration)
        self.assertEqual(geometry["position"], [200., 100., 95.])
        self.assertEqual(calibration["projection_preview"]["reported_camera_pose"]["z"], 100.)
        self.assertIn("preview only", " ".join(blockers))

    def test_preview_rejects_changed_view_intrinsics_and_invalid_correction(self):
        calibration, intrinsics = self.preview_calibration()
        with self.assertRaisesRegex(ValueError, "left the measured view"):
            camera_geometry_for_scan(pose(x=202.), intrinsics, calibration)
        with self.assertRaisesRegex(ValueError, "intrinsics changed"):
            camera_geometry_for_scan(pose(), dict(intrinsics, fx=91.), calibration)
        calibration["projection_preview"]["camera_pose_world"]["z"] = float("nan")
        with self.assertRaisesRegex(ValueError, "valid camera_pose"):
            camera_geometry_for_scan(pose(), intrinsics, calibration)

    def test_without_preview_uses_reported_camera_geometry(self):
        calibration, intrinsics = self.preview_calibration()
        del calibration["projection_preview"]
        geometry, blockers = camera_geometry_for_scan(pose(), intrinsics, calibration)
        self.assertEqual(geometry["position"], [200., 100., 100.])
        self.assertEqual(blockers, [])

    async def test_preview_cannot_transfer_even_if_reference_flag_is_true(self):
        calibration, _ = self.preview_calibration()
        calibration["reference"]["verified"] = True
        backend = ViamInventoryBackend(allow_motion=True)
        backend.current_pose = AsyncMock()
        with patch("bouquet_vision.load_calibration", return_value=calibration), self.assertRaisesRegex(RuntimeError, "Preview camera"):
            await backend.transfer({"pickable": True}, AsyncMock())
        backend.current_pose.assert_not_awaited()

    async def test_readonly_transfer_and_stop_never_call_hardware(self):
        backend = ViamInventoryBackend(allow_motion=False)
        backend.bot = type("FakeBot", (), {"arm": type("Arm", (), {"stop": AsyncMock()})(),
                                          "gripper": type("Grip", (), {"stop": AsyncMock()})()})()
        backend._motion_started = True
        with self.assertRaises(RuntimeError):
            await backend.transfer({}, AsyncMock())
        with self.assertRaises(RuntimeError):
            await backend.return_to_scan()
        await backend.stop()
        backend.bot.arm.stop.assert_not_awaited()
        backend.bot.gripper.stop.assert_not_awaited()

    async def test_detector_and_color_share_exact_frame(self):
        image = Image.new("RGB", (128, 72), "white")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        frame = NamedImage("color", buffer.getvalue(), CameraMimeType.JPEG)
        metadata = ResponseMetadata()
        metadata.captured_at.FromDatetime(datetime.now(timezone.utc))
        backend = ViamInventoryBackend()
        backend.robot = object()
        backend._resource_names = ("cam", "vision-1")
        backend.camera = type("FakeCamera", (), {
            "get_images": AsyncMock(return_value=([frame], metadata)),
            "get_properties": AsyncMock(return_value=GetPropertiesResponse(
                intrinsic_parameters=IntrinsicParameters(width_px=128, height_px=72,
                                                         focal_x_px=90, focal_y_px=90,
                                                         center_x_px=64, center_y_px=36)))})()
        backend.detector = type("FakeVision", (), {"get_detections": AsyncMock(return_value=[
            Detection(x_min=10, y_min=10, x_max=30, y_max=60, confidence=.9, class_name="stem")])})()
        backend.current_pose = AsyncMock(return_value=pose())
        calibration = default_calibration()
        calibration.update(image_size=[128, 72], scan_pose=pose(), scan_camera_pose=pose())
        snapshot = {"ready": False, "blockers": ["Unverified reference"], "candidates": [],
                    "detections": [], "colors": [], "occupied_slot_ids": []}
        with patch("bouquet_vision.load_calibration", return_value=calibration), \
             patch("bouquet_localization.table_inventory", return_value=snapshot) as table:
            result = await backend.scan()
        self.assertEqual(result["mode"], "live")
        self.assertIs(backend.detector.get_detections.await_args.args[0], frame)
        self.assertEqual(table.call_args.args[0][0]["class_name"], "stem")
        self.assertEqual(table.call_args.args[1].size, (128, 72))
        self.assertTrue(backend.jpeg)

    async def test_resource_name_change_refuses_old_camera_model(self):
        backend = ViamInventoryBackend()
        backend.robot = object()
        backend._resource_names = ("cam", "vision-1")
        backend.capture_frame = AsyncMock()
        calibration = dict(default_calibration(), camera="different-camera")
        with patch("bouquet_vision.load_calibration", return_value=calibration):
            result = await backend.scan()
        self.assertEqual(result["mode"], "offline")
        self.assertIn("resource names changed", result["blockers"][0])
        backend.capture_frame.assert_not_awaited()

    async def test_unverified_slot_calibration_cannot_execute(self):
        backend = ViamInventoryBackend(allow_motion=True)
        backend.current_pose = AsyncMock()
        calibration = dict(default_calibration(), version=1, mode="slots")
        backend.snapshot = {"ready": True}
        with patch("bouquet_vision.load_calibration", return_value=calibration), self.assertRaisesRegex(RuntimeError, "verified"):
            await backend.transfer({"pickable": True}, AsyncMock())
        backend.current_pose.assert_not_awaited()

    def test_rotation_wrap_uses_full_pose(self):
        a, b = pose(), pose()
        a["theta"], b["theta"] = 179., -181.
        self.assertTrue(pose_matches(a, b))
        b["theta"] = 150
        self.assertFalse(pose_matches(a, b))

    def test_tracker_rejects_ambiguous_identity(self):
        tracker = DetectionTracker()
        def candidate(key, x):
            return {"id": key, "bbox": [x, 10, x + 10, 100], "color": "red", "pickable": True, "blockers": []}
        tracker.update({"candidates": [candidate("a", 10)], "occupied_slot_ids": ["a"], "colors": [], "ready": True})
        snapshot = tracker.update({"candidates": [candidate("b", 12), candidate("c", 18)],
                                   "occupied_slot_ids": ["b", "c"], "colors": [], "ready": True})
        self.assertFalse(snapshot["ready"])
        self.assertTrue(all(not c["pickable"] for c in snapshot["candidates"]))


class BouquetApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = DemoInventoryBackend()
        self.client = TestClient(TestServer(await bouquet.build_app(backend=self.backend)))
        try:
            await self.client.start_server()
        except BaseException:
            await self.client.close()
            raise

    async def asyncTearDown(self):
        await self.client.close()

    async def test_demo_two_red_order_through_http(self):
        payload = {"items": [{"color": "red", "quantity": 2}]}
        response = await self.client.post("/api/plan", json=payload)
        self.assertTrue((await response.json())["ready"])
        response = await self.client.post("/api/orders", json=payload)
        self.assertEqual(response.status, 202)
        for _ in range(100):
            order = await (await self.client.get("/api/orders/current")).json()
            if order["status"] != "running":
                break
            await asyncio.sleep(.025)
        self.assertEqual(order["status"], "completed", order)
        self.assertEqual(order["completed"], 2)
        self.assertEqual([c["color"] for c in self.backend.candidates].count("red"), 0)

    async def test_cross_origin_order_rejected(self):
        result = await self.client.post("/api/orders", json={}, headers={"Origin": "https://different-site.invalid"})
        self.assertEqual(result.status, 403)

    async def test_scan_and_stop_accept_empty_post_body(self):
        scan = await self.client.post("/api/scan")
        self.assertEqual(scan.status, 200)
        stop = await self.client.post("/api/stop")
        self.assertEqual(stop.status, 200)

    async def test_unavailable_stock_never_starts_transfer(self):
        self.backend.transfer = AsyncMock()
        result = await self.client.post("/api/orders", json={"items": [{"color": "red", "quantity": 3}]})
        self.assertEqual(result.status, 409)
        self.backend.transfer.assert_not_awaited()


class ProductionTablePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_localizer_tracker_and_order_controller_handle_two_red(self):
        # Import shared synthetic scene data, but run the real three production layers.
        from test_bouquet_localization import calibration, detection, geometry, rose_image
        from bouquet_localization import table_inventory
        from bouquet_orders import OrderController

        class TableBackend:
            def __init__(self):
                self.xs, self.picked = [80, 220], []
                self.tracker = DetectionTracker()

            async def scan(self):
                result = table_inventory([detection(x) for x in self.xs], rose_image(self.xs), calibration(), geometry())
                for candidate in result["candidates"]:
                    normalize_table_candidate(candidate)
                    candidate.update(localization_mode="table", calibration_digest="constant-tested-calibration")
                self.tracker.update(result)
                result.update(mode="demo", detected_at=utc_now())
                return result

            async def transfer(self, candidate, on_stage):
                self.picked.append(candidate["id"])
                x = round((candidate["bbox"][0] + candidate["bbox"][2]) / 2)
                self.xs.remove(x)
                await on_stage("released")

            async def return_to_scan(self):
                pass

            async def stop(self):
                pass

            async def close(self):
                pass

        backend = TableBackend()
        controller = OrderController(backend)
        try:
            await controller.start({"items": [{"color": "red", "quantity": 2}]})
            for _ in range(100):
                if controller.current()["status"] != "running":
                    break
                await asyncio.sleep(.01)
            self.assertEqual(controller.current()["status"], "completed", controller.current())
            self.assertEqual(controller.current()["completed"], 2)
            self.assertEqual(len(set(backend.picked)), 2)
        finally:
            await controller.close()


if __name__ == "__main__":
    unittest.main()
