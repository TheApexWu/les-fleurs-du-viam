# Say it with flowers: Viam hackathon plan (16-17 Oct 2026)

**Pitch:** type a feeling; the arm composes an ikebana-style arrangement on a kenzan to express it. A vision model that never sees the request then guesses the feeling from a photo, and the robot makes the one edit that would make it read better.

**The claim to prove with a control:** composition, not just flower choice, carries the meaning. Same stems, random placement vs planned placement: how often does the blind critic guess right?

## Before 9:00 Fri
- Jamali Floral & Garden, 149 W 28th St (opens 6am):
  - kenzan 6-8 cm
  - shallow heavy dish
  - floral foam as backup
- Stems from the W 28th St wholesalers: stiff, bold, distinct colours, ~10 (expect breakage).
- `pip install -r requirements.txt`; `.env` holds the Viam address and keys (from the CONNECT tab) plus ANTHROPIC_API_KEY.

## Friday: milestones (stop and fix before moving on)
| time | milestone | done when |
|---|---|---|
| 9:30-10:30 | kickoff, team, hardware | **RealSense D435, not Orbbec Astra 2** (its depth starts at 0.6 m); arm + gripper + camera show READY |
| 10:30-11:30 | **M0 bring-up** | `resources` lists everything; `grip_test` holds a stem firmly without crushing (tune GRIP_STEM); every VERIFY line checked |
| 11:30-12:30 | **teach** | jig with numbered slots, stems upright; `teach slot0..slot4`, `teach kenzan` (gripper TCP at pin tops, centre), `teach photo` |
| 12:30-1:00 | **M1 one stem** | `insert_one` picks slot 0 and seats it vertically in the kenzan, 3 times in a row |
| 2:00-4:00 | **M2 three lines** | `sogetsu` places shin/soe/hikae at clamped tilts, back to front, no collisions |
| 4:00-6:00 | **M3 eyes** | `photo` from a fixed pose; `ai.critique(photo)` returns valid JSON on 3 test photos; fill `inventory.json` |
| 6:00-8:30 | **M4 loop** | `say gratitude`: plan → arrange → photo → critic guess + edit, end to end once |
| 8:30-9:00 | **safety net** | record a clean M2 run on video; commit; note what broke |

## Saturday
- 9:30-11:30: **control experiment.**
  - 3 sentiments × (planned vs random_baseline), critic guesses blind.
  - Log the accuracy table.
  - That table is the demo's headline.
- 11:30-12:30: apply one critic edit (pull and reinsert one stem) if time allows; otherwise show the edit as text.
- 1:30-3:15: rehearse. Make sure the demo works with the AI off (scripted sogetsu) if the API or wifi fails.
- 3:30: demo, about 3 minutes:
  1. Type a feeling.
  2. Watch it arrange.
  3. Show the critic's blind guess.
  4. Show the control table.

## Rules
- **Don't try to see stems.** They're too thin for depth at arm's length. The jig and taught poses are the perception.
- **Tilts are capped at 30°** (`MAX_TILT_DEG`). The plan keeps the wanted tilt so the gap is visible. Raise the cap only after M2 is solid.
- **Every move passes placed stems as obstacles;** insert back to front.
- **The critic only ever sees the photo and the list of 8 sentiments,** never the request.
- **Fallbacks:** the planner falls back to Sogetsu basic, and a critique failure logs and continues.

## Risks
1. **Stem slips or buckles.** Stiff stems, a set grip width (not `grab()`), foam tape on the grip point, foam instead of kenzan.
2. **Planner fails at angled poses.** Validate every target before running; lower the tilt cap; teach a joint-space fallback.
3. **Taught pose frame is wrong** (arm base vs world, gripper TCP offset). Check `teach` output against the 3D scene before M1.
