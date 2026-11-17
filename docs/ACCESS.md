# Switching devices on and off

Cursor AI checks `access.json` (repo root, `main` branch) at start, every 30 minutes, and before each capture.

1. The person using the app opens **Device Access**, clicks **Copy**, and sends you the Device ID (12 characters, a hash of their computer, not the raw hardware ID).
2. You run, in a clone of the repo:
   ```
   python3 tools/access.py block a1b2c3d4e5f6 --name "Ali"      # switch off
   python3 tools/access.py allow a1b2c3d4e5f6                   # switch back on
   python3 tools/access.py list
   git add access.json && git commit -m access && git push
   ```
   Other options: `mode allowlist` (only listed devices work), `everyone off` (global switch), `message "text"`, `remove <id>`.
3. The device is off within about 15 minutes, or at its next capture/restart.

Limits: the repo is public, so `access.json` and device names are public. Use nicknames. The check is client-side in open-source code: someone who edits the app or stays offline from the start can bypass it. A device that was blocked and then goes offline stays blocked (saved copy). It is meant for people you gave the app to, not for security.

## Dashboard (who is using it)
See `server/README.md`. With it you also get a live list of every device, who is online or using the app now, and Block/Allow buttons that act within a minute.

**Whitelist:** new devices are blocked until you click Approve in the dashboard (switchable). A device that has not been approved cannot take captures, even offline.
