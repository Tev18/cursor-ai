#!/usr/bin/env python3
"""Owner tool: switch devices on/off by editing access.json, then push it.

  python3 tools/access.py list
  python3 tools/access.py block  <device-id> [--name "Ali's MacBook"]     (switch a device off)
  python3 tools/access.py allow  <device-id> [--name "Ali's MacBook"]     (switch it back on / add it to the allowlist)
  python3 tools/access.py remove <device-id>
  python3 tools/access.py mode blocklist|allowlist       blocklist: everyone is on unless blocked. allowlist: only allowed devices.
  python3 tools/access.py everyone off|on                global switch
  python3 tools/access.py message "Text shown to blocked devices"

The Device ID is shown in each person's Cursor AI app under "Device Access" (they can copy it and send it to you).
The repo is public, so device names in access.json are public too: use first names or nicknames.
After a change:  git add access.json && git commit -m "access" && git push
"""
import argparse, json, os, re, sys

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "access.json")


def load():
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        d = {}
    d.setdefault("enabled", True); d.setdefault("mode", "blocklist"); d.setdefault("message", ""); d.setdefault("devices", {})
    return d


def save(d):
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False); f.write("\n")


def check_id(i):
    if not re.fullmatch(r"[0-9a-f]{12}", i):
        sys.exit("Device ID must be 12 hex characters, like a1b2c3d4e5f6 (copy it from the app's Device Access card).")
    return i


def main(argv=None):
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("block", "allow"):
        s = sub.add_parser(c); s.add_argument("id"); s.add_argument("--name")
    s = sub.add_parser("remove"); s.add_argument("id")
    s = sub.add_parser("mode"); s.add_argument("value", choices=["blocklist", "allowlist"])
    s = sub.add_parser("everyone"); s.add_argument("value", choices=["on", "off"])
    s = sub.add_parser("message"); s.add_argument("text")
    a = p.parse_args(argv); d = load()
    if a.cmd == "list":
        print("everyone: %s   mode: %s" % ("on" if d["enabled"] else "OFF", d["mode"]))
        for i, e in d["devices"].items():
            print("  %s  %-24s %s" % (i, e.get("name", ""), "on" if e.get("enabled", True) else "OFF"))
        return 0
    if a.cmd in ("block", "allow"):
        i = check_id(a.id); e = d["devices"].setdefault(i, {})
        if a.name: e["name"] = a.name
        e["enabled"] = a.cmd == "allow"
    elif a.cmd == "remove":
        d["devices"].pop(check_id(a.id), None)
    elif a.cmd == "mode":
        d["mode"] = a.value
    elif a.cmd == "everyone":
        d["enabled"] = a.value == "on"
    elif a.cmd == "message":
        d["message"] = a.text
    save(d); print("Saved access.json. Now: git add access.json && git commit -m access && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
