#!/bin/bash
# Sync Claude Code config FROM local environment TO this repo
# Run this before committing to keep the repo up-to-date
# Usage: bash sync-to-repo.sh [project_root]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect project root
if [ -n "$1" ]; then
    PROJECT_ROOT="$1"
else
    PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
fi

MEMORY_PATH_SEGMENT=$(echo "$PROJECT_ROOT" | sed 's|^/||; s|/|-|g')
CLAUDE_MEMORY_DIR="$HOME/.claude/projects/-${MEMORY_PATH_SEGMENT}/memory"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"

echo "=== Syncing Claude Config to Repo ==="
echo "From: $CLAUDE_MEMORY_DIR"
echo "To:   $SCRIPT_DIR"
echo ""

# Sync memory files
if [ -d "$CLAUDE_MEMORY_DIR" ]; then
    for f in "$CLAUDE_MEMORY_DIR"/*.md; do
        if [ -f "$f" ]; then
            cp "$f" "$SCRIPT_DIR/memory/"
            echo "  <- memory/$(basename "$f")"
        fi
    done
fi

# Sync hooks
if [ -f "$CLAUDE_HOOKS_DIR/session-init.sh" ]; then
    cp "$CLAUDE_HOOKS_DIR/session-init.sh" "$SCRIPT_DIR/"
    echo "  <- session-init.sh"
fi

# Sync CLAUDE.md from tomoshi-site
TOMOSHI_CLAUDE="$PROJECT_ROOT/tomoshi-site/CLAUDE.md"
if [ -f "$TOMOSHI_CLAUDE" ]; then
    cp "$TOMOSHI_CLAUDE" "$SCRIPT_DIR/CLAUDE.md"
    echo "  <- CLAUDE.md (from tomoshi-site)"
fi

echo ""
echo "Done. Now commit and push:"
echo "  cd $(dirname "$SCRIPT_DIR") && git add claude-config/ && git commit -m 'sync claude config' && git push"
