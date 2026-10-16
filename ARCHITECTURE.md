# How Les Fleurs du Viam works

Diagrams render on GitHub. "Live" means read from armfarm12 on 16 Oct afternoon; "planned" means not built or not run yet.

## 1. The pieces and where they run

```mermaid
flowchart LR
  subgraph Laptop["Laptop (our code, this repo)"]
    D["dashboard.py<br/>browser teleop :8765"]
    T["teleop.py<br/>terminal teleop"]
    C["fleurs_core.py<br/>limits, one move at a time,<br/>per-move log + 5 Hz trace"]
    F["flowers.py<br/>pick / drop / fill steps<br/>plan-only check before every move"]
    R["recorder.py<br/>snapshots while hand-guiding"]
    A["ai.py<br/>Claude planner + blind critic"]
    G["geometry.py / composition.py<br/>pose maths, stem-in-vase model"]
    D --> C
    T --> C
    F --> G
    F --> A
  end

  subgraph Cloud["Viam cloud"]
    APP["Viam app<br/>CONFIGURE, CONTROL, 3D SCENE"]
    DATA["Data (rose_logger uploads)"]
  end

  subgraph Robot["armfarm12 compute box (viam-server 1.12.0)"]
    ARM["arm (xArm)"]
    GR["gripper"]
    CAM["cam (colour + depth)"]
    MOT["builtin motion service<br/>planner + obstacles"]
    OBS["obstacles: table, wall-front,<br/>wall-side, ceiling"]
    V["vase (generic, frame only)"]
    VIS["vision: yolo8-rose-detection,<br/>flower_color_detector-cyan/-orange"]
    DM["rose_logger (data manager)"]
    MOD["fleurs teleop module<br/>(planned, viam_module/)"]
  end

  C -- "gRPC over WebRTC" --> ARM
  F -- "motion.do_command plan, then motion.move" --> MOT
  F --> CAM
  R --> ARM
  MOT --> ARM
  MOT --> OBS
  APP <--> Robot
  DM --> DATA
  MOD -.-> ARM
```

## 2. What is on the Viam platform right now (live, 16 Oct ~2:45 pm)

| Resource | Type | Who | Notes |
|---|---|---|---|
| `arm` | component, xArm via viam-ufactory-xarm | cell | TCP 105 mm past the flange |
| `gripper` | component | cell | width and speed go through the **arm's** DoCommand |
| `cam` | component, colour + depth | cell | on the wrist, 83 mm behind the flange |
| `table`, `wall-front`, `wall-side`, `ceiling` | obstacles (box geometry) | cell | table top at z -23 per config (not yet touch-checked) |
| `builtin` | motion service | cell | supports the plan-only DoCommand |
| `vase` | generic component | team | **a frame at (360, 234, 118) with no shape**, so the planner doesn't avoid it |
| `yolo8-rose-detection` | vision service | team | rose detector |
| `flower_color_detector-cyan`, `-orange` | vision service | team | colour detectors |
| `rose_logger` | data manager | team | data capture to the cloud |

**Open question:** our arm-measured vase is at (300, -283), rim z 420. The team's `vase` frame is at (360, 234). Either the vase moved to the +y side or one of the two is wrong. `config.VASE` must match where the vase actually is, or the obstacle box protects the wrong spot.

## 3. One pick-and-place, step by step (planned flow for `vase_one`)

```mermaid
sequenceDiagram
  participant Op as Operator
  participant F as flowers.py
  participant M as motion service
  participant A as arm + gripper
  Op->>F: python flowers.py vase_one 0
  F->>F: best_lean(): score 6 lean directions by clearance to placed stems, blooms, gripper
  F->>A: setup: speeds, gripper speed
  loop every move
    F->>M: do_command {"plan": MoveRequest}  (dry run, never moves)
    alt no full plan
      M-->>F: error or plan_partialwp
      F-->>Op: refuse, nothing moved
    else plan OK
      F->>M: motion.move (same request)
      M->>A: execute
    end
  end
  Note over F,A: pick: above slot -> straight down (slow) -> close -> check width -> straight up
  Note over F,A: drop: hub at travel height -> along stem axis to 10 cm above rim -> open -> back out -> hub
  F->>F: record the placed stem as obstacles (stem box + bloom cube) for the next drop
```

## 4. Teleop to automation (the path we're on)

```mermaid
flowchart LR
  H["Drive by hand<br/>dashboard, hold-to-move"] --> L["Log: every move<br/>+ 5 Hz trace + marks"]
  L --> K["Keyframes<br/>approach, grasp, lift,<br/>over vase, release"]
  K --> P["Replay as joint moves<br/>(same path every time)"]
  P --> S["Shift per rose slot<br/>= pick_and_place(slot)"]
  S --> V["Later: camera finds the rose<br/>(team's detectors) instead of a slot"]
```

## 5. Measured limits that shape the design

| Fact | Value | How we know |
|---|---|---|
| Teleop accuracy | median 0.13 mm, max 0.2 mm over 103 moves | dashboard logs |
| Highest reachable point over the vase, gripper down | z 600 (680 unreachable) | plan-only checks |
| Wrist angle over the vase | -105° works; -15° makes the wrist hit the camera | plan-only checks |
| Stem allowed below the fingers when crossing the rim | about 140 mm | rim 420 + margin vs z 600 |
| Lean a vase allows | about 18-25° whatever the release angle | our model and a MuJoCo drop test, assumed vase depth |
| Gripper vs placed stems | the gripper, not the flowers, limits the third stem | clearance model |

What this means: top-down grabs can only carry a stem gripped close to its bottom. Roses with the bloom above the grip need the side grasp (gripper horizontal) that people naturally used in manual mode. That path is not plan-checked yet.
