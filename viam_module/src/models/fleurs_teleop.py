"""Viam generic service: drive the arm with the same limits and recording as teleop.py.

Use it from the app's CONTROL tab (DoCommand on this service):
  {"command": "key", "key": "r"}          one jog; keys as in teleop.py (w s a d r f q e j l o c g, "\t", " ")
  {"command": "stop"}                     stop the arm now
  {"command": "mark", "label": "grasp"}   label this moment in the recording
  {"command": "state"}                    latest pose, joints, gripper, step size
  {"command": "log_tail", "n": 10}        the last n replies

Config attributes: {"arm": "arm"} required; optional "vase" {x, y, rim_z, rim_r}, "table_top_z",
"grip_stem", "grip_speed". Recordings go to $VIAM_MODULE_DATA (or /tmp/fleurs-du-viam) on the robot.
"""
import asyncio
import os
from typing import ClassVar, Mapping, Optional, Sequence, Tuple

from typing_extensions import Self
from viam.components.arm import Arm
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.services.generic import Generic
from viam.utils import ValueTypes, struct_to_dict

import fleurs_core as core


class FleursTeleop(Generic, EasyResource):
    MODEL: ClassVar[Model] = Model(ModelFamily("apexwu", "fleurs-du-viam"), "teleop")

    @classmethod
    def validate_config(cls, config: ComponentConfig) -> Tuple[Sequence[str], Sequence[str]]:
        attrs = struct_to_dict(config.attributes)
        if not isinstance(attrs.get("arm"), str):
            raise Exception('"arm" (the arm component name) is required')
        return [attrs["arm"]], []

    @classmethod
    def new(cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]) -> Self:
        self = super().new(config, dependencies)
        attrs = struct_to_dict(config.attributes)
        core.configure(vase=attrs.get("vase"), table_top_z=attrs.get("table_top_z"),
                       grip_speed=attrs.get("grip_speed"), grip_stem=attrs.get("grip_stem"),
                       log_dir=os.environ.get("VIAM_MODULE_DATA", "/tmp/fleurs-du-viam"))
        arm = next(d for n, d in dependencies.items() if n.name == attrs["arm"])
        self.jog = core.Jogger(arm)
        self.replies: list[str] = []
        self._start = asyncio.create_task(self.jog.start())
        return self

    async def do_command(self, command: Mapping[str, ValueTypes], *, timeout: Optional[float] = None,
                         **kwargs) -> Mapping[str, ValueTypes]:
        cmd = command.get("command", "key" if "key" in command else "")
        if cmd == "stop":
            msg = await self.jog.stop()
        elif cmd == "key":
            msg = await self.jog.handle(str(command.get("key", "")))
        elif cmd == "mark":
            msg = await self.jog.handle("m", str(command.get("label", "")))
        elif cmd == "state":
            return {"latest": self.jog.latest or {}, "last": self.jog.last,
                    "step_mm": core.STEPS_MM[self.jog.step_i], "busy": self.jog.busy.locked(),
                    "log": str(self.jog.log_path)}
        elif cmd == "log_tail":
            return {"lines": self.replies[-int(command.get("n", 10)):]}
        else:
            raise Exception(f"unknown command {cmd!r}; use key, stop, mark, state or log_tail")
        self.replies.append(msg)
        return {"msg": msg}

    async def close(self):
        self.jog.close()
