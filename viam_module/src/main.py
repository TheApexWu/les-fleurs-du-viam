import asyncio

from viam.module.module import Module

from models.fleurs_teleop import FleursTeleop  # noqa: F401 - importing registers the model

if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())
