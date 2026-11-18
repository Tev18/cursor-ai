"""Version and update source. The release workflow rewrites REPO and UPDATE_PUBLIC_KEY at build time."""
VERSION = "1.0.8"
REPO = "Tev18/cursor-ai"        # "owner/name" of the GitHub repository that hosts the releases
UPDATE_PUBLIC_KEY = ""          # base64 raw Ed25519 public key used to verify release signatures

# The owner's device dashboard (server/README.md). With it set, this app works like a whitelist: a device must be
# approved by the owner before captures are allowed. Leave empty for an app with no access control.
ACCESS_SERVER = "https://cursor-ai-devices.yoyo-34b.workers.dev"
