#!/usr/bin/env python3
"""Writes the release source into mac/version.py and windows/version.py.

  python3 tools/stamp_version.py --repo owner/cursor-ai [--key BASE64_PUBLIC_KEY] [--version 1.2.3]
"""
import argparse, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo"); p.add_argument("--key"); p.add_argument("--version")
    a = p.parse_args()
    if a.repo and not re.match(r"^[\w.-]+/[\w.-]+$", a.repo):
        sys.exit("--repo must look like owner/name")
    if a.version and not re.match(r"^\d+\.\d+\.\d+(-[\w.]+)?$", a.version):
        sys.exit("--version must look like 1.2.3")
    for sub in ("mac", "windows"):
        path = os.path.join(ROOT, sub, "version.py")
        s = open(path, encoding="utf-8").read()
        if a.repo is not None:
            s = re.sub(r'^REPO = ".*?"', f'REPO = "{a.repo}"', s, flags=re.M)
        if a.key is not None:
            s = re.sub(r'^UPDATE_PUBLIC_KEY = ".*?"', f'UPDATE_PUBLIC_KEY = "{a.key}"', s, flags=re.M)
        if a.version:
            s = re.sub(r'^VERSION = ".*?"', f'VERSION = "{a.version}"', s, flags=re.M)
        open(path, "w", encoding="utf-8").write(s)
    print("updated mac/version.py and windows/version.py")


main()
