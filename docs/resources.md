# Resources

Checked links, grouped by what they're for. "Verified" means we opened the source on 16 Oct.

**Viam**
- Python SDK reference: https://python.viam.dev
- Builtin motion service source, incl. the plan-only DoCommand and `plan_file_path` / `log_planner_errors` (verified): https://github.com/viamrobotics/rdk/blob/v1.12.0/services/motion/builtin/builtin.go
- Fake arm with `"arm-model": "xarm6"` for dry runs in the 3D SCENE (verified): https://github.com/viamrobotics/rdk/blob/v1.12.0/components/arm/fake/fake.go
- xArm module: DoCommands (manual mode, gripper, speed, `load`), `collision_sensitivity`, URDFs: https://github.com/viam-modules/viam-ufactory-xarm
- Writing a logic module (generic service, DoCommand): https://docs.viam.com/build-modules/write-a-logic-module/
- Input controllers (gamepad, webgamepad): https://docs.viam.com/hardware/common-components/add-an-input-controller/
- Docs index for AI agents: https://docs.viam.com/llms.txt
- Viam's own xArm6 + RealSense pick-and-place workshop (no licence; read, don't copy): https://github.com/viam-devrel/pick-and-place
- Detections to 3D segments: https://github.com/viam-modules/detections-to-segments
- Colour detector vision service: https://docs.viam.com/reference/services/vision/color_detector/
- YOLOv8 as a Viam vision module: https://github.com/viam-labs/YOLOv8
- Local 3D visualiser for frames and point clouds: https://github.com/viamrobotics/visualization
- Viam MCP / agent kit: https://github.com/viamrobotics/viam-agentic-kit

**Simulation**
- MuJoCo (loads the xArm6 URDF, CPU on a Mac): https://mujoco.readthedocs.io
- Genesis, soft-body stems later: https://github.com/Genesis-Embodied-AI/Genesis
- Isaac Sim behind Viam APIs (needs an NVIDIA GPU): https://github.com/viam-modules/viam-isaac-sim

**Perception**
- YOLOE open-vocabulary detection + masks: https://docs.ultralytics.com/models/yoloe/
- SAM 2 (box-prompted masks): https://github.com/facebookresearch/sam2
- OWLv2 (one-shot image-guided detection): https://huggingface.co/docs/transformers/model_doc/owlv2

**Learning from demonstrations and grasping**
- LeRobot (ACT, diffusion policy, dataset format): https://github.com/huggingface/lerobot
- Movement primitives (replay one demo toward new goals): https://github.com/dfki-ric/movement_primitives
- Stem grasping from RGB-D, closest research code (GPL-3.0): https://github.com/StructuresComp/robotic-pollination
- Contact-GraspNet (6-DoF grasps; needs CUDA): https://github.com/NVlabs/contact_graspnet

**Arrangement and evaluation**
- Ikebana proportions (shin / soe / hikae): https://www.sunset.com/home-garden/flowers-plants/ikebana-flower-arranging-basics
- CLIP zero-shot second critic: https://github.com/mlfoundations/open_clip
- Rater agreement for blind ratings: https://github.com/pln-fing-udelar/fast-krippendorff
