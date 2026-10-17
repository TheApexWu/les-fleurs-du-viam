"""Serialized bouquet orders with fresh inventory checks between physical picks.

The backend owns camera calibration and arm execution. This controller never
derives robot coordinates from pixels and never retries a failed physical pick.
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from bouquet_core import plan_order

logger = logging.getLogger(__name__)


EMPTY_INVENTORY_BLOCKER = "No detected stem has a calibrated pickup and reliable color evidence."
VERIFICATION = (
    "Completion checks the gripper release and that the flower's source location cleared. "
    "The flower landing in the vase is not camera- or sensor-verified."
)


def _now():
    return datetime.now(timezone.utc).isoformat()


class OrderRejected(Exception):
    """An actionable API rejection that occurred before starting an order."""

    def __init__(self, status, payload):
        self.status = status
        self.payload = payload if isinstance(payload, dict) else {"error": str(payload)}
        super().__init__(self.payload.get("error", "Order rejected."))


class OrderController:
    """Run one bouquet at a time against an async vision/robot backend.

    Backend methods: scan(), transfer(candidate, on_stage), return_to_scan(),
    stop(), and close(). ``on_stage`` is an async callback receiving a string.
    ``scan`` must return same-frame inventory at the calibrated scan pose and
    include mode, detected_at, ready, blockers, candidates, occupied_slot_ids.
    """

    def __init__(self, backend, allow_motion=False, max_snapshot_age_s=10):
        if (isinstance(max_snapshot_age_s, bool)
                or not isinstance(max_snapshot_age_s, (int, float))
                or not math.isfinite(max_snapshot_age_s) or max_snapshot_age_s <= 0):
            raise ValueError("max_snapshot_age_s must be a positive finite number.")
        self.backend = backend
        self.allow_motion = allow_motion
        self.max_snapshot_age_s = max_snapshot_age_s
        self._lock = asyncio.Lock()
        self._task = None
        self._order = None
        self._closed = False
        self._generation = 0
        self._stop_requests = 0

    def current(self):
        """Return a detached public order; polling never reads or moves hardware."""
        return deepcopy(self._order)

    def _available(self):
        if self._closed:
            raise OrderRejected(503, "The bouquet controller is closed; restart the server.")
        if self._stop_requests:
            raise OrderRejected(409, "A stop is in progress; wait for it to finish before scanning or ordering.")
        if self._task is not None and not self._task.done():
            raise OrderRejected(409, "A bouquet order is already running; wait or stop it first.")

    async def _scan_backend(self):
        try:
            snapshot = await self.backend.scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Inventory scan failed")
            raise OrderRejected(503, f"Inventory scan failed: {exc}. Check the camera and vision service.") from exc
        if not isinstance(snapshot, Mapping):
            raise OrderRejected(503, "The camera backend returned malformed inventory; scan again.")
        return deepcopy(snapshot)

    def _validate_snapshot(self, snapshot, *, allow_empty=False, require_motion=False):
        mode = snapshot.get("mode")
        if mode not in ("live", "demo"):
            raise OrderRejected(409, {"error": "Inventory is offline; connect the machine and scan again.",
                                      "blockers": list(snapshot.get("blockers") or [])})
        if require_motion and mode == "live" and not self.allow_motion:
            raise OrderRejected(403, "Live arm execution is disabled. Restart with explicit live-motion permission.")
        raw_time = snapshot.get("detected_at")
        try:
            if not isinstance(raw_time, str):
                raise ValueError("missing timestamp")
            captured = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if captured.tzinfo is None:
                raise ValueError("timestamp has no timezone")
            age = (datetime.now(timezone.utc) - captured).total_seconds()
        except (ValueError, TypeError, OverflowError) as exc:
            raise OrderRejected(409, "Inventory has no valid capture timestamp; scan again.") from exc
        if age < -2 or age > self.max_snapshot_age_s:
            raise OrderRejected(409, "Inventory is stale or its clock is incorrect; scan again before picking.")
        blockers = snapshot.get("blockers") or []
        if not isinstance(blockers, list) or any(not isinstance(item, str) for item in blockers):
            raise OrderRejected(409, "Inventory blockers are malformed; scan again.")
        remaining = [item for item in blockers if not (allow_empty and item == EMPTY_INVENTORY_BLOCKER)]
        empty_only = allow_empty and bool(blockers) and not remaining
        if remaining or (snapshot.get("ready") is not True and not empty_only):
            error = "Inventory is not ready for a calibrated pick."
            if snapshot.get("raw_detection_count") == 0 and snapshot.get("flower_detections"):
                error = (f"Flower heads were detected, but {snapshot.get('vision_service', 'the stem detector')} "
                         "returned zero stems in the fresh frame; pickup is blocked.")
            raise OrderRejected(409, {"error": error,
                                      "blockers": remaining or ["Recheck calibration and the scan pose."]})

    async def scan(self):
        async with self._lock:
            self._available()
            return await self._scan_backend()

    def _apply_run_limits(self, plan):
        limit = getattr(self.backend, "max_order_size", 12)
        if plan.get("requested_total", 0) > limit:
            plan["blockers"].append(f"This session accepts at most {limit} flowers per order.")
            plan["ready"], plan["assignments"] = False, []
        if getattr(self.backend, "commissioning_used", False):
            plan["blockers"].append("The single commissioning attempt is used; inspect the result before restarting.")
            plan["ready"], plan["assignments"] = False, []
        sequence = getattr(self.backend, "order_sequence", None)
        if sequence:
            plan["assignments"].sort(key=lambda candidate: sequence.index(candidate["slot_id"]))
        return plan

    async def plan(self, payload):
        async with self._lock:
            self._available()
            snapshot = await self._scan_backend()
            plan = self._apply_run_limits(plan_order(payload, snapshot))
            try:
                self._validate_snapshot(snapshot)
            except OrderRejected as exc:
                plan["ready"] = False
                plan["assignments"] = []
                plan["blockers"] = list(dict.fromkeys(
                    plan["blockers"] + [exc.payload["error"]] + exc.payload.get("blockers", [])))
            return plan

    async def start(self, payload):
        """Rescan and validate the full bouquet before scheduling any motion."""
        async with self._lock:
            self._available()
            generation = self._generation
            snapshot = await self._scan_backend()
            if generation != self._generation or self._closed:
                raise OrderRejected(409, "Order submission was cancelled while scanning; create a new order when ready.")
            self._validate_snapshot(snapshot, require_motion=True)
            plan = self._apply_run_limits(plan_order(payload, snapshot))
            if not plan["ready"]:
                raise OrderRejected(409, {"error": "The requested bouquet cannot be built from this scan.",
                                          "blockers": plan["blockers"], "plan": plan})
            assignments = plan["assignments"]
            ids = [candidate.get("id") for candidate in assignments]
            slots = [candidate.get("slot_id") for candidate in assignments]
            if len(ids) != len(set(ids)) or len(slots) != len(set(slots)):
                raise OrderRejected(409, "Inventory repeats a rose or pickup location; rescan before ordering.")
            now = _now()
            self._order = {
                "id": uuid4().hex, "status": "running", "stage": "accepted",
                "requested_total": plan["requested_total"], "completed": 0,
                "steps": [], "items": deepcopy(plan["items"]), "rules": deepcopy(plan["rules"]),
                "mode": snapshot["mode"], "verification": getattr(self.backend, "verification", VERIFICATION),
                "error": None, "failure_stage": None, "created_at": now, "updated_at": now,
            }
            self._record("accepted")
            self._task = asyncio.create_task(self._run(deepcopy(assignments)),
                                             name=f"bouquet-{self._order['id']}")
            return self.current()

    def _record(self, stage, candidate=None):
        self._order["stage"] = stage
        self._order["updated_at"] = _now()
        event = {"stage": stage, "time": self._order["updated_at"]}
        if candidate:
            event.update(candidate_id=candidate["id"], slot_id=candidate["slot_id"], color=candidate["color"],
                         variety=candidate.get("variety", "rose"))
        self._order["steps"].append(event)
        logger.info("order=%s stage=%s candidate=%s flower=%s:%s completed=%s/%s",
                    self._order["id"], stage, event.get("candidate_id", "-"),
                    event.get("variety", "-"), event.get("color", "-"),
                    self._order["completed"], self._order["requested_total"])

    def _fresh_candidate(self, expected, snapshot):
        candidates = snapshot.get("candidates", [])
        if not isinstance(candidates, list):
            raise RuntimeError("Inventory candidates are malformed; rescan before retrying.")
        matching = [candidate for candidate in candidates if isinstance(candidate, Mapping)
                    and candidate.get("id") == expected["id"]]
        if len(matching) != 1:
            raise RuntimeError(f"Stem {expected['id']} is missing or ambiguous; inspect inventory and create a new order.")
        current = matching[0]
        occupied = snapshot.get("occupied_slot_ids")
        if not isinstance(occupied, list) or expected["slot_id"] not in occupied:
            raise RuntimeError(f"Rose occupancy at source location {expected['slot_id']} cannot be confirmed; scan again.")
        if (current.get("slot_id") != expected["slot_id"] or current.get("color") != expected["color"]
                or current.get("variety", "rose") != expected.get("variety", "rose")
                or current.get("pickable") is not True):
            raise RuntimeError(f"Stem {expected['id']} changed color, source location or pickup readiness; rescan and reorder.")
        if current.get("localization_mode") != expected.get("localization_mode"):
            raise RuntimeError("Pickup localization changed during the order; verify calibration and reorder.")
        if expected.get("localization_mode") == "table":
            self._validate_table_refresh(expected, current)
        else:
            if current.get("pickup_poses") != expected.get("pickup_poses"):
                raise RuntimeError(f"Pickup calibration for {expected['slot_id']} changed during the order; verify it and reorder.")
            if ("calibration_digest" in expected and "calibration_digest" in current
                    and expected["calibration_digest"] != current["calibration_digest"]):
                raise RuntimeError(f"Calibration changed for {expected['slot_id']} during the order; verify it and reorder.")
        # Reuse the pure planner to validate all current candidate fields, including poses.
        check = plan_order({"items": [{"variety": expected.get("variety", "rose"), "color": expected["color"], "quantity": 1}]},
                           dict(snapshot, candidates=[current]))
        if not check["ready"]:
            raise RuntimeError("Current pickup is no longer valid: " + "; ".join(check["blockers"]))
        return deepcopy(current)

    @staticmethod
    def _validate_table_refresh(expected, current):
        """Allow bounded same-stem measurement noise, never a new physical target."""
        digest = expected.get("calibration_digest")
        if not isinstance(digest, str) or not digest or current.get("calibration_digest") != digest:
            raise RuntimeError("Calibration changed or is missing during table localization; verify it and reorder.")

        def vector(row, key, lengths):
            value = row.get(key)
            if (not isinstance(value, (list, tuple)) or len(value) not in lengths
                    or any(isinstance(n, bool) or not isinstance(n, (int, float))
                           or not math.isfinite(n) for n in value)):
                raise RuntimeError(f"Stem {key} is invalid; rescan before attempting a pickup.")
            return list(value)

        old_point = vector(expected, "world_grasp", (3,))
        new_point = vector(current, "world_grasp", (3,))
        if math.dist(old_point, new_point) > 10:
            raise RuntimeError("Stem position shifted by more than 10 mm; rescan and create a new order.")
        axes = [vector(row, "world_axis", (2, 3)) for row in (expected, current)]
        normalized = []
        for axis in axes:
            length = math.hypot(*axis)
            if length <= 1e-9:
                raise RuntimeError("Stem world_axis has zero length; rescan before attempting a pickup.")
            normalized.append([component / length for component in axis] + [0] * (3 - len(axis)))
        # The axis points from the cut/base toward the blossom. A 180-degree
        # reversal changes the required gripper yaw and must not be accepted.
        alignment = sum(a * b for a, b in zip(*normalized))
        if alignment < math.cos(math.radians(10)):
            raise RuntimeError("Stem orientation shifted by more than 10 degrees; rescan and create a new order.")

    async def _run(self, assignments):
        candidate = None
        try:
            for candidate in assignments:
                self._record("rescan_before_pick", candidate)
                snapshot = await self._scan_backend()
                self._validate_snapshot(snapshot, require_motion=True)
                if snapshot["mode"] != self._order["mode"]:
                    raise RuntimeError("Inventory backend mode changed during the order; restart the order.")
                current = self._fresh_candidate(candidate, snapshot)

                async def on_stage(stage):
                    self._record(str(stage), candidate)

                self._record("transfer", candidate)
                await self.backend.transfer(current, on_stage)
                self._record("return_to_scan", candidate)
                await self.backend.return_to_scan()
                self._record("verify_source_clear", candidate)
                after = await self._scan_backend()
                self._validate_snapshot(after, allow_empty=True, require_motion=True)
                if after["mode"] != self._order["mode"]:
                    raise RuntimeError("Inventory backend mode changed during source verification.")
                occupied = after.get("occupied_slot_ids")
                if not isinstance(occupied, list) or any(not isinstance(slot, str) for slot in occupied):
                    raise RuntimeError("The scan cannot verify source occupancy; inspect the gripper and source before retrying.")
                if candidate["slot_id"] in occupied:
                    raise RuntimeError(f"Source location {candidate['slot_id']} is still occupied or ambiguous after release; inspect the rose before a new order.")
                self._order["completed"] += 1
                self._record("flower_completed", candidate)
            self._order["status"] = "completed"
            self._record("completed")
        except asyncio.CancelledError:
            self._order["status"] = "cancelled"
            self._record("cancelled", candidate)
            raise
        except Exception as exc:
            self._order["failure_stage"] = self._order["stage"]
            self._order["status"] = "failed"
            message = str(exc)
            if isinstance(exc, OrderRejected) and exc.payload.get("blockers"):
                message += " " + "; ".join(exc.payload["blockers"])
            self._order["error"] = message
            logger.exception("order=%s failed stage=%s: %s", self._order["id"],
                             self._order["failure_stage"], message)
            self._record("failed", candidate)
            try:
                await self.backend.stop()
            except Exception as stop_error:
                logger.exception("order=%s stop after failure failed", self._order["id"])
                self._order["error"] += f" Stop request also failed: {stop_error}. Use the machine stop."

    async def stop(self):
        """Cancel further picks and explicitly stop hardware, without opening jaws."""
        # Invalidate a submission immediately, even when it owns the mutex while
        # awaiting a camera frame. It must never schedule a pick after this stop.
        self._generation += 1
        self._stop_requests += 1
        try:
            async with self._lock:
                task = self._task
                active = task is not None and not task.done()
                if active:
                    self._record("stopping")
                    task.cancel()
                stop_error = None
                try:
                    await self.backend.stop()
                except Exception as exc:
                    stop_error = exc
                if active:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    self._order["status"] = "cancelled"
                    if self._order["stage"] != "cancelled":
                        self._record("cancelled")
                if stop_error is not None:
                    if self._order:
                        self._order["error"] = f"Stop request failed: {stop_error}. Use the machine stop."
                    raise OrderRejected(503, f"Stop request failed: {stop_error}. Use the machine stop.") from stop_error
                return self.current()
        finally:
            self._stop_requests -= 1

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        # An in-flight start may currently be awaiting its first scan under this
        # lock. Wait for it to finish before deciding whether cleanup must stop it.
        async with self._lock:
            active = self._task is not None and not self._task.done()
        try:
            if active:
                await self.stop()
        finally:
            await self.backend.close()
