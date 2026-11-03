#!/bin/sh
# One-shot init: migrations + seed, then topics/subscriptions in the emulator.
set -e
echo "[init] migrating + seeding"
python scripts/migrate.py
echo "[init] creating Pub/Sub topics and subscriptions"
python scripts/setup_pubsub.py
echo "[init] done"
