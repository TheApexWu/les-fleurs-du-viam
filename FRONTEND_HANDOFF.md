# Frontend handoff

- Branch: `frontend/bouquet-studio`
- Repository: <https://github.com/TheApexWu/les-fleurs-du-viam>
- Base: `pretend-loop` at `fa8c8bd`.

This branch contains the Bouquet Studio frontend and a standalone preview
server. The bouquet backend, vision/localization work, and robot changes are
being developed separately; `bouquet.py` is not included here.

## Start on your machine

You need Git, Python 3.10 or newer, and a modern browser. There is no npm install,
build step, virtual environment, API key, or robot connection for the preview.

```sh
git clone --branch frontend/bouquet-studio https://github.com/TheApexWu/les-fleurs-du-viam.git
cd les-fleurs-du-viam
python3 bouquet_ui/preview.py
```

Open <http://127.0.0.1:8000/?demo=1>. On Windows, use
`py -3 bouquet_ui/preview.py` if `python3` is unavailable. If port 8000 is busy,
add `--port 8001` and open the printed URL. Stop the server with Ctrl+C.

For an existing clean checkout:

```sh
git fetch origin
git switch --track origin/frontend/bouquet-studio
python3 bouquet_ui/preview.py
```

If the local branch already exists, use `git switch frontend/bouquet-studio`.
Keep any existing local edits safe before changing branches. To work in a
separate directory without switching your current checkout, use:

```sh
git fetch origin
git worktree add -b frontend/my-bouquet-work ../fleurs-frontend origin/frontend/bouquet-studio
cd ../fleurs-frontend
python3 bouquet_ui/preview.py
```

The preview opens with two red roses selected and sample counts of red 6,
pink 4, white 5, yellow 3. A visible **PREVIEW MODE** banner confirms that the
browser is simulating everything locally. The preview server only serves files;
it implements no API and connects to no hardware.

Do not open `index.html` directly or use a plain `http.server` from this
directory: the page expects its assets under `/static/`. The supplied preview
server maps those paths for you. Optional Google Fonts have local fallbacks.

## Where to look

| File | Responsibility |
| --- | --- |
| `bouquet_ui/index.html` | Page structure, botanical SVG art, controls, accessible status regions |
| `bouquet_ui/styles.css` | Palette, typography, responsive layouts, focus and reduced-motion styles |
| `bouquet_ui/app.js` | Quantities, inventory, plan validation, orders, polling, stop control, local demo |
| `bouquet_ui/README.md` | Backend API contract and integrated behavior |
| `bouquet_ui/preview.py` | Standard-library local static preview, bound to loopback |

Read this guide, then `bouquet_ui/README.md`, then the three UI source files.
The repository's root README mostly describes the robot workflow; its Python
dependencies and hardware setup are unnecessary for frontend work.

## Check your changes

1. Confirm the preview banner, sample inventory, styling, and rose artwork load.
2. Add/remove colors, clear the selection, and check that the summary updates.
   The total is limited to 12 stems. Choosing more than a color's available
   count should fail **Check my bouquet** with a useful message.
3. Check a valid selection, then select **Preview arrangement**. Progress should
   advance once per 1.6 seconds until complete. Changing the selection or
   selection rule must require checking the plan again.
4. Start another preview and select **Stop arm** while it runs. Progress should
   stop and the page should confirm that no robot command was sent.
5. Check at desktop and phone widths, navigate controls with the keyboard,
   and look for browser console errors. The stop control should stay visible.
6. Open <http://127.0.0.1:8000/?demo=0> to inspect the disconnected state:
   inventory becomes unknown, errors are visible, and build stays disabled.
   Return to `?demo=1` for interactive development.

With Node.js installed, `node --check bouquet_ui/app.js` also checks syntax;
Node is optional. There is no frontend package manager or automated UI suite.

## Integration boundaries

The client uses same-origin `/api/` requests. The future bouquet backend serves
the page at `/` and assets at `/static/`; see the API contract in
`bouquet_ui/README.md`. Keep those URLs and payloads compatible, or coordinate
changes with the backend owner. `?demo=1` uses browser-side sample data and sends
no API requests, including for scans, plans, orders, and stop.

Backend `--demo` mode is a separate integration path described in the UI README;
it requires the separately developed backend. The standalone preview does not
test backend polling, camera overlays, live inventory, or real stop handling.
Use backend fixtures or a coordinated backend demo to verify those states.

Keep robot credentials out of browser code. The backend owns camera
interpretation, calibration, planning, and hardware commands. Build remains
gated on an approved plan; disconnected inventory must not show stale counts.
The demo stop only stops the animation. Leave hardware calibration and motion
changes to the robot/backend owner.

## Prompt for the next agent

> You are working on `frontend/bouquet-studio` in les-fleurs-du-viam. Read
> FRONTEND_HANDOFF.md and bouquet_ui/README.md first. Run
> `python3 bouquet_ui/preview.py` and inspect the printed preview URL in a
> browser before editing. Work on the requested frontend changes in
> bouquet_ui/index.html, styles.css, and app.js. Preserve the plain-JavaScript
> setup, API contract, preview labeling, plan gating, unknown-inventory
> behavior, accessible controls, and responsive layout. Check the selection,
> validation, preview progress, stop, and disconnected flows after editing.
> Backend bouquet/vision modules are being developed separately and are absent
> from this branch. Report changes, checks, and any integration dependencies.
