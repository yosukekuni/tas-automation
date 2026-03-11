#!/bin/bash
# Claude Code Environment Setup
# Run this on any new device to restore Claude Code config
# Usage: bash setup.sh [project_root]
#
# project_root: path to the main working directory (default: auto-detect)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Detect project root (where Claude Code is run from)
if [ -n "$1" ]; then
    PROJECT_ROOT="$1"
else
    # Default: parent of tas-automation repo
    PROJECT_ROOT="$(dirname "$REPO_DIR")"
fi

# Convert project root to Claude's memory path format (slashes to dashes)
MEMORY_PATH_SEGMENT=$(echo "$PROJECT_ROOT" | sed 's|^/||; s|/|-|g')
CLAUDE_MEMORY_DIR="$HOME/.claude/projects/-${MEMORY_PATH_SEGMENT}/memory"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

echo "=== Claude Code Environment Setup ==="
echo "Repo:         $REPO_DIR"
echo "Project root: $PROJECT_ROOT"
echo "Memory dir:   $CLAUDE_MEMORY_DIR"
echo ""

# 1. Create directories
mkdir -p "$CLAUDE_MEMORY_DIR"
mkdir -p "$CLAUDE_HOOKS_DIR"

# 2. Copy memory files
echo "[1/4] Syncing memory files..."
cp "$SCRIPT_DIR/memory/MEMORY.md" "$CLAUDE_MEMORY_DIR/"
cp "$SCRIPT_DIR/memory/ai_valueup_division.md" "$CLAUDE_MEMORY_DIR/"
cp "$SCRIPT_DIR/memory/verification_protocol.md" "$CLAUDE_MEMORY_DIR/"
echo "  -> $(ls "$CLAUDE_MEMORY_DIR/" | wc -l) files synced"

# 3. Copy hooks
echo "[2/4] Installing hooks..."
cp "$SCRIPT_DIR/session-init.sh" "$CLAUDE_HOOKS_DIR/"
chmod +x "$CLAUDE_HOOKS_DIR/session-init.sh"
# Fix line endings (in case of Windows CRLF)
sed -i 's/\r$//' "$CLAUDE_HOOKS_DIR/session-init.sh"
echo "  -> session-init.sh installed"

# 4. Copy CLAUDE.md to project directories
echo "[3/4] Installing CLAUDE.md..."
# tomoshi-site
TOMOSHI_DIR="$PROJECT_ROOT/tomoshi-site"
if [ -d "$TOMOSHI_DIR" ]; then
    cp "$SCRIPT_DIR/CLAUDE.md" "$TOMOSHI_DIR/"
    echo "  -> $TOMOSHI_DIR/CLAUDE.md"
fi

# 5. Ensure settings.json has hooks configured
echo "[4/4] Checking settings.json..."
if [ -f "$CLAUDE_SETTINGS" ]; then
    # Check if hooks already configured
    if grep -q "session-init.sh" "$CLAUDE_SETTINGS" 2>/dev/null; then
        echo "  -> Hooks already configured"
    else
        echo "  -> WARNING: session-init.sh hook not in settings.json. Add manually:"
        echo '    "hooks": { "SessionStart": [{ "hooks": [{ "type": "command", "command": "bash ~/.claude/hooks/session-init.sh" }] }] }'
    fi
else
    echo "  -> settings.json not found. Creating minimal config..."
    cat > "$CLAUDE_SETTINGS" << 'SETTINGSEOF'
{
  "permissions": {
    "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebFetch", "WebSearch", "Agent", "NotebookEdit"]
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/session-init.sh"
          }
        ]
      }
    ]
  }
}
SETTINGSEOF
    echo "  -> Created with default config"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Ensure automation_config.json is at: $PROJECT_ROOT/automation_config.json"
echo "  2. Run 'claude' from: $PROJECT_ROOT"
echo "  3. Session will auto-load pending tasks from Lark Base"
echo ""
echo "To sync changes back to repo:"
echo "  bash $SCRIPT_DIR/sync-to-repo.sh"
