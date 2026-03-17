#!/usr/bin/env bash
# Install script for als — the aicoe.fit link shortener CLI.
#
# Usage:
#   curl -fsSL https://aicoe.fit/install | bash
#   wget -qO- https://aicoe.fit/install | bash
#
# Requirements:
#   - Python 3.12 or later
#   - One of: uv, pipx, or pip
#
# What it does:
#   1. Checks for Python 3.12+
#   2. Installs als from the GitHub repository using the best available tool
#   3. Verifies the installation
#
# Environment variables:
#   ALS_VERSION    — Git ref to install (default: main)
#   ALS_QUIET      — Set to 1 to suppress informational output

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

REPO="stephenVertex/aicoe-link-shortener"
PACKAGE_PATH="user-cli"
VERSION="${ALS_VERSION:-main}"
QUIET="${ALS_QUIET:-0}"

# ── Helpers ──────────────────────────────────────────────────────────────────

info() {
  [ "$QUIET" = "1" ] && return
  printf '\033[1;34m==>\033[0m %s\n' "$*"
}

success() {
  printf '\033[1;32m==>\033[0m %s\n' "$*"
}

error() {
  printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
}

die() {
  error "$@"
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# ── Python check ─────────────────────────────────────────────────────────────

check_python() {
  local py=""

  # Try python3 first, then python
  for candidate in python3 python; do
    if command_exists "$candidate"; then
      local ver
      ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || continue
      local major minor
      major="${ver%%.*}"
      minor="${ver#*.}"
      if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
        py="$candidate"
        break
      fi
    fi
  done

  if [ -z "$py" ]; then
    die "Python 3.12 or later is required but not found.

Install Python:
  macOS:   brew install python@3.12
  Ubuntu:  sudo apt install python3.12
  Other:   https://www.python.org/downloads/"
  fi

  info "Found $py ($ver)"
  echo "$py"
}

# ── Install via uv (preferred) ──────────────────────────────────────────────

install_with_uv() {
  local uv_cmd="$1"
  info "Installing als with uv..."
  "$uv_cmd" tool install \
    "als @ git+https://github.com/${REPO}.git@${VERSION}#subdirectory=${PACKAGE_PATH}" \
    --force 2>&1
}

# ── Install via pipx ────────────────────────────────────────────────────────

install_with_pipx() {
  info "Installing als with pipx..."
  pipx install \
    "als @ git+https://github.com/${REPO}.git@${VERSION}#subdirectory=${PACKAGE_PATH}" \
    --force 2>&1
}

# ── Install via pip ──────────────────────────────────────────────────────────

install_with_pip() {
  local py="$1"
  info "Installing als with pip..."
  "$py" -m pip install --user \
    "als @ git+https://github.com/${REPO}.git@${VERSION}#subdirectory=${PACKAGE_PATH}" \
    2>&1
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
  info "Installing als — the aicoe.fit link shortener CLI"
  info ""

  # Step 1: Check Python version
  local py
  py="$(check_python)"

  # Step 2: Install using the best available tool
  local installed=false

  # Prefer uv (fastest, cleanest isolation)
  if command_exists uv; then
    if install_with_uv uv; then
      installed=true
    fi
  fi

  # Fall back to pipx (good isolation)
  if [ "$installed" = false ] && command_exists pipx; then
    if install_with_pipx; then
      installed=true
    fi
  fi

  # Fall back to pip --user (no isolation, but works everywhere)
  if [ "$installed" = false ]; then
    if install_with_pip "$py"; then
      installed=true
    fi
  fi

  if [ "$installed" = false ]; then
    die "Failed to install als. Please install uv, pipx, or pip and try again.

Install uv (recommended):
  curl -LsSf https://astral.sh/uv/install.sh | sh"
  fi

  # Step 3: Verify installation
  echo ""
  if command_exists als; then
    success "als installed successfully!"
    info ""
    info "Quick start:"
    info "  als login --api-key <your-key>    # authenticate"
    info "  als shorten <article-url>          # get tracking link"
    info "  als search <query>                 # search articles"
    info ""
    info "Get your API key from https://admin.aicoe.fit"
  else
    # als might be installed but not on PATH yet (common with pip --user)
    success "als package installed."
    info ""
    info "The 'als' command may not be on your PATH yet."
    info "Try one of:"
    info "  - Open a new terminal"
    info "  - Run: export PATH=\"\$HOME/.local/bin:\$PATH\""
    info "  - Run: hash -r"
    info ""
    info "Then run: als --help"
  fi
}

main
