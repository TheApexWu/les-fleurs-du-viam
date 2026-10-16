# Friday 16 Oct: plan and mental model

**Goal for today: pick one rose from its holder and place it in the vase, 3 times in a row.**
Everything else waits until that works.

## Mental model (read once, it decides everything below)

1. **A pose is the fingertip point.** Viam reports the gripper's TCP (tool centre point), set 105 mm past the wrist flange. If the real black fingertips reach further than that, every taught height is off by the difference. Check it once (task B2).

2. **Roses must be grabbed from the side.** A bloom sits above where we grip, so grabbing from straight above would push the bloom into the wrist. The gripper points sideways (horizontal), fingers close across the stem, and the stem stays upright. Top-down grabs only work for a bare stick held near its top. **The current drop code assumes top-down and must be redone for side grasp (task C1).**

3. **What hangs below the fingers sets the travel height.** While carrying, the stem's foot must clear the vase rim, so travel height = rim + length below grip + 4 cm. The arm can't reach much above z ~800 over the vase, so **keep the length below the grip under ~25 cm**: trim stems, and grip lower.

4. **The vase decides the lean, not the plan.** A dropped stem settles with its foot on the floor and its body on the rim. Lean ≈ atan(horizontal span / vase depth), only about 15-20° in this vase. We choose *which direction* it leans, not how far.

5. **Three kinds of obstacle.**
   - Static: in the cell config (table, walls, ceiling), plus the vase box (measured) and the power strip (not added yet).
   - Growing: every placed stem (thin box above the rim) and its bloom (cube). The code adds these after each drop.
   - The held stem: the planner doesn't know about it. We protect it by discipline: cross at travel height, descend along the stem's own line, never sweep sideways near the vase.

6. **The gripper, not the flowers, limits how many fit.** With today's sizes, stems and blooms fit 5 with room, but the open gripper hits resting stems by the third drop. So: release ~10 cm above the rim, open the fingers only a little on release, and plan **3 stems** for the demo.

7. **Grip is a set width, not a force.** Rose stems are stiff enough for the default finger speed.

8. **Leaves and thorns snag.** Strip everything from the stem below the bloom's lowest leaf cluster, at least the bottom 25 cm.

9. **Fast in open air, slow near things.** Full speed between holder and vase, slow for the last 10 cm of every grab and drop.

10. **Teaching poses:** run `recorder.py`, hand-guide in manual mode (support the arm from below before pressing the button), hold still for 1 s at each spot, then `promote`. Side-grasp poses keep their hand-taught angle (no `--down`).

11. **Plan before moving, and what it found (16 Oct, 2:45 pm).** Every planned move is now dry-run first. Live checks over the vase: the gripper pointing down reaches z 600 at most, and only with the wrist at -105°. So at most ~14 cm of stem can hang below the fingers when crossing the rim. Roses gripped below the bloom need the side grasp.

## Tasks, in order

### A. Physical prep (anyone, no robot needed)
- [ ] A1. Strip leaves and thorns from the bottom ~25 cm of each stem.
- [ ] A2. Trim to 3 heights so the arrangement has shape, e.g. 45 / 40 / 35 cm. Keep the vase height in mind (looks ~25 cm).
- [ ] A3. Measure each rose: length, bloom width. One stem's thickness. Put them in `config.STEMS`.
- [ ] A4. Measure the vase's inside depth (rim to floor) with a ruler or chopstick. Put it in `config.VASE_DEPTH_MM`.
- [ ] A5. Choose the holder: roses standing upright in the pitcher (recommended; no flipping needed). Tape the pitcher down like the vase.

### B. Measurements on the robot (manual mode + recorder)
- [ ] B1. Touch fingertips flat on the table beside the tape square. Gives the table height and settles the vase-height puzzle.
- [ ] B2. TCP check: in B1, does the reported z equal the table top? If not, the difference is the fingertip offset; correct the gripper frame or the code.
- [ ] B3. Re-measure nothing else unless the vase moves off its tape.

### C. Code (Alex, while A happens)
- [ ] C1. Side-grasp geometry: grip and drop poses with the gripper horizontal and the stem across the fingers; offline tests like the existing ones.
- [ ] C2. Travel height computed from each stem's length below the grip; refuse a move that can't reach.
- [ ] C3. Release opens only ~60 past the stem width.
- [ ] C4. Add the power strip as a box obstacle.

### D. Teleop, then replay (one person at the stop button, every time)
- [ ] D1. Drive one pick-and-place on the dashboard, pressing M at approach, grasp, lift, over vase, release.
- [ ] D2. `python replay.py recordings/teleop-<time>.jsonl`: one slow run.
- [ ] D3. Replay 3 times in a row with the rose in the same spot. **That's today's goal.**
- [ ] D4. A second rose: replay with a base offset, `python replay.py <log> 10`.

### E. If time is left
- [ ] E1. Teach a `photo` pose looking at the vase from the front; `python flowers.py photo` runs the critic.
- [ ] E2. Record a clean run on video as the safety net.

## Risks
- Travel height out of reach with long stems → trim, grip lower (mental model 3).
- Bloom catches the wrist → side grasp only (mental model 2).
- Stem slips in the fingers → calibrate width, strip leaves at the grip point, grip below a node.
- Gripper knocks a placed rose → 3 stems, higher release, roomiest lean (mental model 6).
- Connection drops mid-run → every step can be re-run on its own; the recorder reconnects.

## Who
- **Alex:** C1-C4 (code), decides heights and leans.
- **Manojit (today) / Shaurya (Saturday):** A1-A5, B1-B2, D1-D6 runs and the attempt log.
