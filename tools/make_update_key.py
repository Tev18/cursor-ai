#!/usr/bin/env python3
"""Creates the Ed25519 key pair used to sign releases. Run this ONCE, on your own computer.

  pip install cryptography && python3 tools/make_update_key.py

It prints two values. Nothing is written to disk.
  * PRIVATE key -> GitHub repo > Settings > Secrets and variables > Actions > Secrets:  UPDATE_SIGNING_KEY
  * PUBLIC key  -> same page, "Variables" tab:                                          UPDATE_PUBLIC_KEY
Keep the private key out of the repo and out of chat. If you lose it, generate a new pair; apps built with the old
public key then need a one-time manual reinstall.
"""
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

k = Ed25519PrivateKey.generate()
print("PRIVATE (secret UPDATE_SIGNING_KEY):", base64.b64encode(k.private_bytes_raw()).decode())
print("PUBLIC  (variable UPDATE_PUBLIC_KEY):", base64.b64encode(k.public_key().public_bytes_raw()).decode())
