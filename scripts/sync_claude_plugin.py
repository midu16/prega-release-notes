#!/usr/bin/env python3
"""Copy repo assets into plugins/prega-release-notes/ for the Claude Code marketplace."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN = _ROOT / "plugins" / "prega-release-notes"


def _patch_marketplace_commands(cmd_dir: Path) -> None:
    """Adjust standalone command paths for the plugin install layout."""
    subs = [
        (
            "Work from the **prega-release-notes** repository root (the directory that contains `requirements.txt` and `bin/prega-release-notes`).",
            "Work from this plugin’s root: the directory that contains `requirements.txt`, `bin/prega-release-notes`, and `scripts/` "
            "(when installed via a marketplace, use **`${CLAUDE_PLUGIN_ROOT}`** as `cd` target).",
        ),
        ("cd /path/to/prega-release-notes", 'cd "${CLAUDE_PLUGIN_ROOT}"'),
        (
            "[.cursor/skills/openshift-client-download/SKILL.md](../../.cursor/skills/openshift-client-download/SKILL.md)",
            "[openshift-client-download/SKILL.md](../skills/openshift-client-download/SKILL.md)",
        ),
        (
            "**Slash command:** `/download-clients` (derived from the filename `download-clients.md` under `.claude/commands/`).",
            "**Slash command:** `/download-clients` (from this plugin’s `commands/` directory; when installed as a plugin it may appear namespaced—see `/help`).",
        ),
        (
            "**Load the skill first:** [.cursor/skills/openshift-client-download/SKILL.md](../../.cursor/skills/openshift-client-download/SKILL.md).",
            "**Load the skill first:** [openshift-client-download/SKILL.md](../skills/openshift-client-download/SKILL.md).",
        ),
    ]
    for path in cmd_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        orig = text
        for a, b in subs:
            text = text.replace(a, b)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            print(f"patched {path.relative_to(_ROOT)}")


def _sync() -> None:
    pairs: list[tuple[Path, Path]] = [
        (_ROOT / ".claude" / "commands", _PLUGIN / "commands"),
        (_ROOT / ".cursor" / "skills" / "openshift-client-download", _PLUGIN / "skills" / "openshift-client-download"),
        (_ROOT / ".cursor" / "skills" / "subset-release-notes", _PLUGIN / "skills" / "subset-release-notes"),
        (_ROOT / "scripts", _PLUGIN / "scripts"),
        (_ROOT / "bin", _PLUGIN / "bin"),
        (_ROOT / "requirements.txt", _PLUGIN / "requirements.txt"),
    ]
    for src, dest in pairs:
        if not src.exists():
            print(f"skip missing: {src}", file=sys.stderr)
            continue
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        if src.is_dir():
            shutil.copytree(src, dest, symlinks=True, ignore_dangling_symlinks=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        print(f"updated {dest.relative_to(_ROOT)}")

    _patch_marketplace_commands(_PLUGIN / "commands")
    print("Done.")


if __name__ == "__main__":
    _sync()
