// README-als.md — LLM-readable install + usage guide for als CLI
const README_ALS_MD = `# als — aicoe.fit Link Shortener CLI

\`als\` is a command-line tool for getting personalised tracking links to AI-related
articles indexed at [aicoe.fit](https://aicoe.fit). It uses semantic search to find
articles and returns short, trackable URLs unique to you.

## Install

\`\`\`bash
curl -fsSL aicoe.fit/install | bash
\`\`\`

Or with wget:

\`\`\`bash
wget -qO- aicoe.fit/install | bash
\`\`\`

**Requirements:** Python 3.12+ and [uv](https://docs.astral.sh/uv/). The install
script will install \`uv\` automatically if it is not present.

After installation, add \`~/.local/bin\` to your PATH if it is not already:

\`\`\`bash
export PATH="$HOME/.local/bin:$PATH"
\`\`\`

## Authentication

Get your personal API key from your admin at aicoe.fit, then log in:

\`\`\`bash
als login --api-key als_your_key_here
\`\`\`

Credentials are stored in \`~/.als.credentials\`.

## Commands

### als login

Save your API key for future use.

\`\`\`bash
als login --api-key als_your_key_here
\`\`\`

### als search

Search articles using semantic search and get your personalised tracking links.

\`\`\`bash
als search "GLM-5"
als search "reinforcement learning from human feedback" --count 5
als search "multimodal models"
\`\`\`

Options:
- \`--count INTEGER\` — Number of results to return (default: 3)

### als last

Show the most recently published articles with your personalised tracking links.

\`\`\`bash
als last
als last 5
als last 10 --author "Simon"
als last 3 --author "Anthropic"
\`\`\`

Options:
- \`N\` — Number of articles to show (default: 10)
- \`--author TEXT\` — Filter by author name (case-insensitive substring match)

### als authors

List all authors in the database with their article counts.

\`\`\`bash
als authors
\`\`\`

### als stats

Show statistics about the link shortener database.

\`\`\`bash
als stats
\`\`\`

Output includes:
- Total articles
- Number of authors
- Number of people (tracked users)
- Tracking variants (personalised link variants)
- Total clicks recorded

### als whoami

Show the currently authenticated user.

\`\`\`bash
als whoami
\`\`\`

### als upgrade

Upgrade als to the latest version.

\`\`\`bash
als upgrade
\`\`\`

### als --version

Show the installed version of als.

\`\`\`bash
als --version
\`\`\`

### als --help

Show all available commands.

\`\`\`bash
als --help
als search --help
als last --help
\`\`\`

## Quick Start

\`\`\`bash
# 1. Install
curl -fsSL aicoe.fit/install | bash

# 2. Log in with your API key
als login --api-key als_your_key_here

# 3. Search for articles
als search "GLM-5"

# 4. See the latest 5 articles
als last 5

# 5. See articles by a specific author
als last 5 --author "Simon"

# 6. Browse all authors
als authors

# 7. Check database stats
als stats

# 8. Upgrade when a new version is available
als upgrade
\`\`\`

## Notes for LLMs

- \`als search\` uses semantic (embedding-based) search, not keyword search.
  Natural-language queries work well.
- Each short URL is personalised: the same article produces different short URLs
  for different users, enabling per-user click tracking.
- API keys start with \`als_\` and are issued per-user by an administrator.
- The CLI stores credentials at \`~/.als.credentials\` (mode 0600).
- \`als upgrade\` reinstalls from the canonical wheel on GitHub Releases; it does not require git.
`;

// Install script served at aicoe.fit/install
// Keep in sync with scripts/install.sh
const INSTALL_SCRIPT = `#!/usr/bin/env bash
# Install script for the als CLI (aicoe.fit link shortener)
# Usage: curl -fsSL aicoe.fit/install | bash
#    or: wget -qO- aicoe.fit/install | bash
set -euo pipefail

WHEEL_URL="https://github.com/stephenVertex/aicoe-link-shortener/releases/latest/download/als-py3-none-any.whl"
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

    // README-als.md — LLM-readable install + usage guide
    if (path === "/README-als.md") {
      return new Response(README_ALS_MD, {
        status: 200,
        headers: {
          "Content-Type": "text/markdown; charset=utf-8",
          "Cache-Control": "public, max-age=300",
        },
      });
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
