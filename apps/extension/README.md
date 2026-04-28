# Job Search Pal — Browser Clipper (stub)

Chromium MV3 extension that one-clicks the JD on the current tab into your
local Job Search Pal API as a `to_review` tracked job.

## Status: stub

Working enough for personal use; not packaged or published. Known gaps:

- No real icons — `icons/` is empty so Chrome will warn on load until you
  drop in 16/32/48/128 px PNGs (any colour works).
- Organization is captured as text but not resolved to an `organization_id`;
  the popup stuffs the company name into the job's `notes` field for now.
- Auth assumes the API is open on the LAN OR you're already signed in
  via cookies. There is no token-based auth path.
- "Open in tracker" assumes `web` runs on `:3000` next to the API on
  `:8000`. Wrong if you're tunneling them or behind a reverse proxy.

## Install (developer mode)

1. `chrome://extensions` → toggle **Developer mode** on.
2. Click **Load unpacked** → pick this `apps/extension/` folder.
3. Open the extension's options page and set **API base** if you're not
   running on `http://localhost:8000`.
4. Visit a job posting → click the toolbar icon → **Save**.

## Files

- `manifest.json` — MV3 manifest. `host_permissions` cover loopback only.
- `popup.html` / `popup.js` — the form + extraction + save logic.
- `options.html` / `options.js` — API base URL config.
- `background.js` — placeholder service worker.
- `icons/` — drop 16/32/48/128 px PNGs here.

## Future work (not done)

- Resolve organization name → `organization_id` via `/api/v1/organizations`.
- Context-menu "Save selection as writing sample" → POST `/documents/samples`.
- Pull `fit_score` after save and surface in the popup before the tab closes.
- Bundle as a release with a build step (currently zero deps, zero build).
