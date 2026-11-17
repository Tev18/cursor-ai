#!/usr/bin/env python3
"""Signs release files with the Ed25519 private key in $UPDATE_SIGNING_KEY. Writes <file>.sig next to each file."""
import base64, os, sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = os.environ.get("UPDATE_SIGNING_KEY", "").strip()
if not key:
    sys.exit("UPDATE_SIGNING_KEY is not set")
priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key))
for path in sys.argv[1:]:
    with open(path, "rb") as f:
        sig = priv.sign(f.read())
    with open(path + ".sig", "wb") as f:
        f.write(base64.b64encode(sig))
    print("signed", path)
