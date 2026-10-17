# Frontend work

Read `../FRONTEND_HANDOFF.md` and `README.md` in this directory before editing.
The handoff guide includes local setup, file ownership, manual checks, and
backend integration boundaries.

- Run `python3 bouquet_ui/preview.py` from the repository root. Open the printed
  `?demo=1` URL to inspect the UI without dependencies or robot credentials.
- The frontend is plain HTML, CSS, and JavaScript; keep the existing setup.
- Preserve the `/static/` asset paths and the API contract in this directory's
  README. The bouquet backend is being developed separately.
- Keep the preview visibly labeled, require a successful plan before build,
  clear stale inventory on connection errors, and retain the stop control.
- Verify selection, validation, preview progress/stop, disconnected behavior,
  keyboard access, and phone/desktop layouts after relevant changes.
- Hardware setup and motion execution are outside this frontend handoff.
