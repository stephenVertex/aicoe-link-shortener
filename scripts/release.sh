#!/usr/bin/env bash
# Release script for als CLI
# Usage: ./scripts/release.sh
#
# ⚠️ NOTE: This is the legacy manual release script. The current release process
# is automated via GitHub Actions (.github/workflows/release.yml), which builds
# the wheel, creates a GitHub Release, and deploys the Cloudflare Worker on tag
# push. This script is retained for reference but should not be needed for
# routine releases.
#
# Legacy steps:
#   1. Build the wheel in user-cli/
#   2. Upload the wheel via shup (S3)
#   3. Update WHEEL_URL in scripts/install.sh and worker/src/worker.js
#   4. Deploy via wrangler
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_CLI_DIR="$REPO_ROOT/user-cli"
WORKER_DIR="$REPO_ROOT/worker"
INSTALL_SH="$REPO_ROOT/scripts/install.sh"
WORKER_JS="$REPO_ROOT/worker/src/worker.js"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. Build wheel ----------------------------------------------------------

info "Building wheel in user-cli/..."
cd "$USER_CLI_DIR"
rm -rf dist/
uv build --wheel

WHEEL_FILE="$(ls dist/*.whl | head -1)"
[ -f "$WHEEL_FILE" ] || error "No wheel found in $USER_CLI_DIR/dist/"
info "Built: $WHEEL_FILE"

# --- 2. Upload via shup ------------------------------------------------------

info "Uploading wheel via shup..."
WHEEL_URL="$(shup "$WHEEL_FILE" -p aicoe-link-shortener)"
[ -n "$WHEEL_URL" ] || error "shup returned empty URL"
info "Uploaded: $WHEEL_URL"

# --- 3. Update WHEEL_URL in scripts/install.sh and worker/src/worker.js ------

info "Updating WHEEL_URL in scripts/install.sh..."
sed -i.bak "s|WHEEL_URL=\"[^\"]*\"|WHEEL_URL=\"$WHEEL_URL\"|g" "$INSTALL_SH"
rm -f "$INSTALL_SH.bak"

info "Updating WHEEL_URL in worker/src/worker.js..."
sed -i.bak "s|WHEEL_URL=\"[^\"]*\"|WHEEL_URL=\"$WHEEL_URL\"|g" "$WORKER_JS"
rm -f "$WORKER_JS.bak"

# Verify updates
grep "WHEEL_URL=" "$INSTALL_SH"
grep "WHEEL_URL=" "$WORKER_JS"

# --- 4. Deploy via wrangler --------------------------------------------------

info "Deploying worker via wrangler..."
cd "$WORKER_DIR"
npx wrangler deploy

info "Release complete!"
info "  Wheel URL: $WHEEL_URL"
