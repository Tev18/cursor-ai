# Owner dashboard (who is using Cursor AI)

A tiny Cloudflare Worker + D1 database (both free). It shows everyone who ever used the app, who is online right now, who is taking captures, and lets you Block / Allow / Forget a device. Only you can open it: the page asks for an admin key that only you know. Each app reports once a minute: person's name (if they typed one), device name, Device ID, system, app version, capture count, last active time. **Never** screenshots, answers, prompts, API keys or IP addresses. The Device Access card in the app tells people this.

## Set it up (about 10 minutes, once)
1. Sign in at dash.cloudflare.com (free account) -> **Workers & Pages** -> **Create** -> **Create Worker**. Name it `cursor-ai-devices` -> **Deploy**.
2. Click **Edit code**. Delete everything, paste the whole of `server/worker.js` from this repo, click **Deploy**.
3. Create the database: left menu **Storage & Databases** -> **D1 SQL Database** -> **Create database**, name `cursor-ai`. (The Worker creates its table by itself.)
4. Back in your Worker -> **Settings** -> **Bindings** -> **Add** -> **D1 database**. Variable name: `DB` (exactly). Pick `cursor-ai`. Save.
5. Worker -> **Settings** -> **Variables and secrets** -> **Add** -> type **Secret**, name `ADMIN_KEY`, value: a long random password (24+ characters; the Worker refuses anything under 12). Deploy. Save this key somewhere safe: it is the only way into the dashboard.
6. Open `https://cursor-ai-devices.<your-subdomain>.workers.dev/admin`, enter the admin key. Bookmark it.
7. Tell the apps where to report: edit `access.json` in this repo and add your Worker URL (https only, no trailing slash):
   ```
   { "server": "https://cursor-ai-devices.<your-subdomain>.workers.dev", "enabled": true, "mode": "blocklist", "message": "...", "devices": {} }
   ```
   Within 15 minutes (or at next launch) every app on v1.0.5+ starts reporting.

## Using it
- **Status**: *Using now* = took a capture in the last 5 minutes; *Online* = heard from in the last 2.5 minutes; *Offline* otherwise; *Blocked* = you switched it off.
- **Block** switches a device off within a minute (its next heartbeat). **Allow** switches it back on. **Forget** removes the row (it reappears if that device runs the app again).
- Free limits: D1 allows 100,000 writes/day, about 65 always-on devices at one heartbeat a minute.

## Notes
- Anyone can send pings to `/ping` (that is how apps report), so the list can be spammed with fake devices; **Forget** removes them. Blocking and reading always need your admin key.
- It is a soft control: the app is open source and runs on the user's computer, so a determined person can edit it or stay offline. Older app versions (before 1.0.5) do not report.
- Test the Worker logic yourself: `node server/test.mjs` (Node 22+).
