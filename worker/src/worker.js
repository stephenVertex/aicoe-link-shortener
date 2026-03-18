// Install script served at aicoe.fit/install
// Keep in sync with scripts/install.sh
const INSTALL_SCRIPT = `#!/usr/bin/env bash
# Install script for the als CLI (aicoe.fit link shortener)
# Usage: curl -fsSL aicoe.fit/install | bash
#    or: wget -qO- aicoe.fit/install | bash
set -euo pipefail

WHEEL_URL="https://post-genius-media.s3.amazonaws.com/shup/project/aicoe-link-shortener/als-022-py3-none-any.whl"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12

# --- Helpers ----------------------------------------------------------------

info()  { printf '\\033[1;34m==>\\033[0m %s\\n' "$*"; }
warn()  { printf '\\033[1;33mWarning:\\033[0m %s\\n' "$*" >&2; }
error() { printf '\\033[1;31mError:\\033[0m %s\\n' "$*" >&2; exit 1; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

# --- OS detection -----------------------------------------------------------

detect_os() {
    case "$(uname -s)" in
        Linux*)  OS=linux  ;;
        Darwin*) OS=macos  ;;
        *)       error "Unsupported operating system: $(uname -s). Only Linux and macOS are supported." ;;
    esac
    ARCH="$(uname -m)"
    info "Detected: $OS ($ARCH)"
}

# --- Python check -----------------------------------------------------------

check_python() {
    local py=""
    for candidate in python3 python; do
        if command_exists "$candidate"; then
            py="$candidate"
            break
        fi
    done

    if [ -z "$py" ]; then
        warn "Python \${MIN_PYTHON_MAJOR}.\${MIN_PYTHON_MINOR}+ is required but not found."
        warn "uv will manage Python for you, but you may need to install it separately"
        warn "if uv cannot auto-fetch it."
        return
    fi

    local ver
    ver="$($py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)"
    if [ -n "$ver" ]; then
        local major minor
        major="\${ver%%.*}"
        minor="\${ver#*.}"
        if [ "$major" -lt "$MIN_PYTHON_MAJOR" ] || { [ "$major" -eq "$MIN_PYTHON_MAJOR" ] && [ "$minor" -lt "$MIN_PYTHON_MINOR" ]; }; then
            warn "Python $ver found, but als requires \${MIN_PYTHON_MAJOR}.\${MIN_PYTHON_MINOR}+."
            warn "uv will attempt to fetch a suitable Python version automatically."
        else
            info "Python $ver found (meets requirement: \${MIN_PYTHON_MAJOR}.\${MIN_PYTHON_MINOR}+)"
        fi
    fi
}

# --- uv installation --------------------------------------------------------

ensure_uv() {
    if command_exists uv; then
        info "uv is already installed: $(uv --version)"
        return
    fi

    info "Installing uv (Astral package manager)..."
    if command_exists curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command_exists wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        error "Neither curl nor wget found. Please install one of them first."
    fi

    # Source the env file that uv's installer creates, so uv is on PATH
    local uv_env="$HOME/.local/bin/env"
    if [ -f "$uv_env" ]; then
        # shellcheck disable=SC1090
        . "$uv_env"
    fi

    # Also try adding ~/.local/bin and ~/.cargo/bin to PATH directly
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! command_exists uv; then
        error "uv was installed but could not be found on PATH. Please restart your shell and try again."
    fi

    info "uv installed successfully: $(uv --version)"
}

# --- als installation -------------------------------------------------------

install_als() {
    info "Installing als CLI..."
    UV_SKIP_WHEEL_FILENAME_CHECK=1 uv tool install "$WHEEL_URL" --force

    # Verify
    export PATH="$HOME/.local/bin:$PATH"
    if command_exists als; then
        info "als installed successfully: $(als --version 2>&1 || echo 'installed')"
    else
        warn "als was installed but is not on your PATH."
        warn "Add this to your shell profile:"
        warn '  export PATH="$HOME/.local/bin:$PATH"'
        warn "Then restart your shell or run: source ~/.bashrc  (or ~/.zshrc)"
    fi
}

# --- Post-install instructions ----------------------------------------------

print_next_steps() {
    echo ""
    echo "============================================"
    echo "  als CLI installed successfully!"
    echo "============================================"
    echo ""
    echo "  Next steps:"
    echo ""
    echo "  1. Get your API key from your admin at aicoe.fit"
    echo "  2. Log in:      als login --api-key <your-key>"
    echo "  3. Shorten:     als shorten <article-url>"
    echo "  4. Search:      als search <query>"
    echo "  5. Latest:      als last 5"
    echo "  6. Upgrade:     als upgrade"
    echo ""
    echo "  Full help:      als --help"
    echo ""
    if ! command_exists als; then
        echo "  NOTE: You may need to restart your shell or run:"
        echo '    export PATH="$HOME/.local/bin:$PATH"'
        echo ""
    fi
}

# --- Main -------------------------------------------------------------------

main() {
    echo ""
    info "Installing als - the aicoe.fit link shortener CLI"
    echo ""

    detect_os
    check_python
    ensure_uv
    install_als
    print_next_steps
}

main "$@"
`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Skip favicon and robots
    if (path === "/favicon.ico" || path === "/robots.txt") {
      return new Response("", { status: 404 });
    }

    // Install script — serve inline for: curl aicoe.fit/install | bash
    if (path === "/install" || path === "/install.sh") {
      return new Response(INSTALL_SCRIPT, {
        status: 200,
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "public, max-age=300",
        },
      });
    }

    // Root page — redirect to admin dashboard on Amplify
    if (path === "/" || path === "/admin" || path === "/admin/") {
      return new Response(null, {
        status: 302,
        headers: { Location: env.ADMIN_URL || "https://admin.aicoe.fit" },
      });
    }

    // Everything else — redirect logic via the Supabase edge function
    const slug = path.slice(1);
    const targetUrl = `${env.SUPABASE_BASE_URL}/functions/v1/redirect/${slug}`;

    const response = await fetch(targetUrl, {
      method: request.method,
      headers: {
        "user-agent": request.headers.get("user-agent") || "",
        "referer": request.headers.get("referer") || "",
        "x-forwarded-for": request.headers.get("cf-connecting-ip") || "",
        "x-real-ip": request.headers.get("cf-connecting-ip") || "",
      },
      redirect: "manual",
    });

    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  },
};
