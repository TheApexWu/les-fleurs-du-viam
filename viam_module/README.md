# fleurs-du-viam teleop module

The same jog logic as `teleop.py` and `dashboard.py` (one shared file, `fleurs_core.py`), packaged as a
Viam generic service so it can be driven from the Viam app's CONTROL tab.

## Install as an inline module (Viam app)
1. CONFIGURE → `+` → create an inline module, Python, generic service.
2. Paste `src/models/fleurs_teleop.py` as the model file, add `src/fleurs_core.py` next to it,
   and set the entry point to `src/main.py`. Requirements: `requirements.txt`.
3. Save & Deploy, then add the service with these attributes:
   ```json
   {"arm": "arm"}
   ```
   Optional: `"vase": {"x": 300, "y": -283, "rim_z": 420, "rim_r": 59}`, `"table_top_z"`, `"gripper": "gripper"` (enables G = grab).
4. The model triplet in the code is `apexwu:fleurs-du-viam:teleop`; if the app assigns your org's namespace,
   change `ModelFamily(...)` in `fleurs_teleop.py` to match.

## Use (CONTROL tab → this service → DoCommand)
```json
{"command": "key", "key": "r"}
{"command": "stop"}
{"command": "mark", "label": "grasp"}
{"command": "state"}
{"command": "log_tail", "n": 10}
```
Keys: w s a d (x, y), r f (z), q e (wrist), j l (base swing), o c g (gripper), "\t" (step size).

After editing `../fleurs_core.py`, run `./sync.sh` so the module's copy matches.
Smoke-tested offline against a fake arm (keys, limits, mark, stop, state, unknown command); not yet deployed.
