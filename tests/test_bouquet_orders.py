"""Offline orchestration tests: inventory changes never trigger blind retries."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bouquet_orders import EMPTY_INVENTORY_BLOCKER, OrderController, OrderRejected


def candidate(name, color="red"):
    pose = {"x": 100, "y": 0, "z": 300, "o_x": 0, "o_y": 0, "o_z": 1, "theta": 0}
    return {"id": name, "slot_id": name, "color": color, "confidence": 0.95,
            "pickable": True, "blockers": [], "bbox": [10, 10, 20, 20],
            "pickup_poses": {key: dict(pose) for key in ("pickup_approach", "pretend_grasp", "lift")}}


def order(quantity=2):
    return {"items": [{"color": "red", "quantity": quantity}]}


def table_candidate(name="red-1"):
    return dict(candidate(name), localization_mode="table", calibration_digest="table-calibration",
                world_grasp=[100, 200, 5], world_axis=[1, 0])


class FakeBackend:
    def __init__(self, stock=None):
        self.stock = deepcopy(stock if stock is not None else [candidate("red-1"), candidate("red-2")])
        self.mode = "demo"
        self.transfers = []
        self.transferred_candidates = []
        self.returns = 0
        self.stops = 0
        self.closed = False
        self.scans = 0
        self.fail_transfer = False
        self.fail_after_release = False
        self.keep_source = False
        self.global_blockers = []
        self.stale = False
        self.block_transfer = False
        self.transfer_started = asyncio.Event()
        self.release_transfer = asyncio.Event()
        self.scan_hook = None
        self.block_scan_at = None
        self.scan_started = asyncio.Event()
        self.release_scan = asyncio.Event()

    async def scan(self):
        self.scans += 1
        if self.scans == self.block_scan_at:
            self.scan_started.set()
            await self.release_scan.wait()
        if self.scan_hook:
            self.scan_hook(self)
        timestamp = datetime.now(timezone.utc) - timedelta(seconds=30 if self.stale else 0)
        blockers = self.global_blockers + ([] if self.stock else [EMPTY_INVENTORY_BLOCKER])
        return {"mode": self.mode, "detected_at": timestamp.isoformat(), "ready": bool(self.stock) and not blockers,
                "blockers": blockers,
                "candidates": deepcopy(self.stock), "occupied_slot_ids": [row["slot_id"] for row in self.stock]}

    async def transfer(self, row, on_stage):
        self.transfers.append(row["id"])
        self.transferred_candidates.append(deepcopy(row))
        self.transfer_started.set()
        await on_stage("grasp")
        if self.block_transfer:
            await self.release_transfer.wait()
        if self.fail_transfer:
            raise RuntimeError("Gripper did not confirm a stem; inspect pickup before retrying.")
        if not self.keep_source:
            self.stock = [item for item in self.stock if item["slot_id"] != row["slot_id"]]
        await on_stage("release")
        if self.fail_after_release:
            raise RuntimeError("Release verification failed; inspect the gripper before retrying.")

    async def return_to_scan(self):
        self.returns += 1

    async def stop(self):
        self.stops += 1

    async def close(self):
        self.closed = True


class OrderControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = FakeBackend()
        self.controller = OrderController(self.backend)

    async def asyncTearDown(self):
        await self.controller.close()

    async def finish(self):
        await asyncio.wait_for(asyncio.shield(self.controller._task), 1)
        return self.controller.current()

    async def test_two_red_roses_use_two_distinct_transfers_and_source_checks(self):
        started = await self.controller.start(order())
        self.assertEqual(started["status"], "running")
        result = await self.finish()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(self.backend.transfers, ["red-1", "red-2"])
        self.assertEqual(self.backend.returns, 2)
        self.assertEqual(self.backend.scans, 5)  # submission + before/after each pick
        self.assertIn("not camera- or sensor-verified", result["verification"])
        result["steps"].clear()
        self.assertTrue(self.controller.current()["steps"])

    async def test_stock_shortage_rejects_before_any_motion(self):
        with self.assertRaises(OrderRejected) as rejection:
            await self.controller.start(order(3))
        self.assertIn("only 2", str(rejection.exception.payload["blockers"]))
        self.assertEqual(self.backend.transfers, [])
        self.assertEqual(self.backend.returns, 0)
        self.assertIsNone(self.controller.current())

    async def test_concurrent_starts_and_scans_cannot_interleave_motion(self):
        self.backend.block_transfer = True
        results = await asyncio.gather(self.controller.start(order()), self.controller.start(order()),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(result, OrderRejected) for result in results), 1)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        await self.backend.transfer_started.wait()
        scan_count = self.backend.scans
        with self.assertRaises(OrderRejected):
            await self.controller.scan()
        with self.assertRaises(OrderRejected):
            await self.controller.plan(order())
        self.assertEqual(self.backend.scans, scan_count)
        await self.controller.stop()

    async def test_failed_grasp_never_completes_or_attempts_second_pick(self):
        self.backend.fail_transfer = True
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failure_stage"], "grasp")
        self.assertEqual(self.backend.transfers, ["red-1"])
        self.assertEqual(self.backend.stops, 1)

    async def test_stale_submission_is_rejected_before_any_motion(self):
        self.backend.stale = True
        with self.assertRaises(OrderRejected) as rejected:
            await self.controller.start(order())
        self.assertIn("stale", str(rejected.exception))
        self.assertEqual(self.backend.transfers, [])

    async def test_stop_during_submission_scan_prevents_scheduling_a_pick(self):
        self.backend.block_scan_at = 1
        submission = asyncio.create_task(self.controller.start(order()))
        await self.backend.scan_started.wait()
        stopping = asyncio.create_task(self.controller.stop())
        await asyncio.sleep(0)
        self.backend.release_scan.set()
        with self.assertRaises(OrderRejected) as rejected:
            await submission
        await stopping
        self.assertIn("cancelled while scanning", str(rejected.exception))
        self.assertEqual(self.backend.transfers, [])
        self.assertIsNone(self.controller.current())
        self.assertEqual(self.backend.stops, 1)

    async def test_transfer_failure_after_release_event_does_not_count_a_flower(self):
        self.backend.fail_after_release = True
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failure_stage"], "release")
        self.assertEqual(self.backend.transfers, ["red-1"])
        self.assertEqual(self.backend.returns, 0)
        self.assertEqual(self.backend.stops, 1)

    async def test_post_pick_global_blocker_prevents_count_even_if_source_cleared(self):
        def calibration_changed(backend):
            if backend.scans == 3:
                backend.global_blockers = ["Camera calibration changed; verify the scan pose."]
        self.backend.scan_hook = calibration_changed
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["failure_stage"], "verify_source_clear")
        self.assertIn("Camera calibration changed", result["error"])
        self.assertEqual(self.backend.transfers, ["red-1"])
        self.assertEqual(self.backend.stops, 1)

    async def test_changed_calibration_digest_rejects_before_transfer(self):
        self.backend.stock[0]["calibration_digest"] = "original-calibration"
        def calibration_changed(backend):
            if backend.scans == 2:
                backend.stock[0]["calibration_digest"] = "changed-calibration"
        self.backend.scan_hook = calibration_changed
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertIn("Calibration changed", result["error"])
        self.assertEqual(self.backend.transfers, [])

    async def test_table_candidate_uses_latest_bounded_measurement_and_aligned_axis(self):
        self.backend.stock = [table_candidate()]
        def refine_measurement(backend):
            if backend.scans == 2:
                row = backend.stock[0]
                row["world_grasp"] = [103, 204, 5]
                row["world_axis"] = [1, 0, 0]  # same cut/base-to-blossom direction
                row["pickup_poses"]["pretend_grasp"]["x"] = 103
        self.backend.scan_hook = refine_measurement
        await self.controller.start(order(1))
        result = await self.finish()
        self.assertEqual(result["status"], "completed")
        moved = self.backend.transferred_candidates[0]
        self.assertEqual(moved["world_grasp"], [103, 204, 5])
        self.assertEqual(moved["pickup_poses"]["pretend_grasp"]["x"], 103)

    async def test_table_candidate_large_position_shift_prevents_any_transfer(self):
        self.backend.stock = [table_candidate()]
        def move_stem(backend):
            if backend.scans == 2:
                backend.stock[0]["world_grasp"][0] += 11
        self.backend.scan_hook = move_stem
        await self.controller.start(order(1))
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertIn("10 mm", result["error"])
        self.assertEqual(self.backend.transfers, [])

    async def test_table_candidate_large_orientation_shift_prevents_any_transfer(self):
        self.backend.stock = [table_candidate()]
        def rotate_stem(backend):
            if backend.scans == 2:
                backend.stock[0]["world_axis"] = [0.95, 0.31]
        self.backend.scan_hook = rotate_stem
        await self.controller.start(order(1))
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertIn("10 degrees", result["error"])
        self.assertEqual(self.backend.transfers, [])

    async def test_table_candidate_flipped_axis_prevents_any_transfer(self):
        self.backend.stock = [table_candidate()]
        def reverse_stem_direction(backend):
            if backend.scans == 2:
                backend.stock[0]["world_axis"] = [-1, 0, 0]
        self.backend.scan_hook = reverse_stem_direction
        await self.controller.start(order(1))
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertIn("10 degrees", result["error"])
        self.assertEqual(self.backend.transfers, [])

    async def test_table_candidate_missing_digest_or_invalid_axis_prevents_transfer(self):
        for key, value in (("calibration_digest", None), ("world_axis", [0, 0]),
                           ("world_grasp", [float("nan"), 0, 0])):
            with self.subTest(key=key):
                self.backend.stock = [table_candidate()]
                self.backend.stock[0][key] = value
                await self.controller.start(order(1))
                result = await self.finish()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.backend.transfers, [])

    async def test_stale_rescan_fails_before_first_transfer(self):
        self.backend.scan_hook = lambda backend: setattr(backend, "stale", backend.scans > 1)
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.backend.transfers, [])

    async def test_source_still_occupied_fails_without_retry(self):
        self.backend.keep_source = True
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertIn("still occupied", result["error"])
        self.assertEqual(result["failure_stage"], "verify_source_clear")
        self.assertEqual(self.backend.transfers, ["red-1"])
        self.assertEqual(self.backend.stops, 1)

    async def test_stop_cancels_current_pick_and_prevents_later_motion(self):
        self.backend.block_transfer = True
        await self.controller.start(order())
        await self.backend.transfer_started.wait()
        stopped = await self.controller.stop()
        self.backend.release_transfer.set()
        await asyncio.sleep(0)
        self.assertEqual(stopped["status"], "cancelled")
        self.assertEqual(stopped["completed"], 0)
        self.assertEqual(self.backend.transfers, ["red-1"])
        self.assertEqual(self.backend.returns, 0)
        self.assertEqual(self.backend.stops, 1)

    async def test_stop_immediately_after_start_also_records_cancelled(self):
        await self.controller.start(order())
        result = await self.controller.stop()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.backend.transfers, [])
        self.assertEqual(self.backend.stops, 1)

    async def test_live_motion_is_explicit_and_demo_is_allowed(self):
        self.backend.mode = "live"
        with self.assertRaises(OrderRejected) as rejected:
            await self.controller.start(order())
        self.assertEqual(rejected.exception.status, 403)
        self.assertEqual(self.backend.transfers, [])

    async def test_candidate_that_changes_color_is_not_substituted(self):
        def change_color(backend):
            if backend.scans == 2:
                backend.stock[0]["color"] = "yellow"
        self.backend.scan_hook = change_color
        await self.controller.start(order())
        result = await self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.backend.transfers, [])
        self.assertIn("changed color", result["error"])

    async def test_duplicate_candidate_ids_rejected_before_any_motion(self):
        self.backend.stock[1]["id"] = self.backend.stock[0]["id"]
        with self.assertRaises(OrderRejected):
            await self.controller.start(order())
        self.assertEqual(self.backend.transfers, [])

    async def test_close_stops_active_order_and_closes_backend(self):
        self.backend.block_transfer = True
        await self.controller.start(order())
        await self.backend.transfer_started.wait()
        await self.controller.close()
        self.assertEqual(self.controller.current()["status"], "cancelled")
        self.assertTrue(self.backend.closed)
        self.assertEqual(self.backend.stops, 1)


if __name__ == "__main__":
    unittest.main()
