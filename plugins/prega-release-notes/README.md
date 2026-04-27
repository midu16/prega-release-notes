# prega-release-notes (Claude Code plugin)

This directory is the **Claude Code plugin payload** for the [midu16-prega](https://github.com/midu16/prega-release-notes/blob/main/.claude-plugin/marketplace.json) marketplace.

After `claude plugin install prega-release-notes@midu16-prega`, use **`${CLAUDE_PLUGIN_ROOT}`** as the working directory when running `bin/prega-release-notes` or `scripts/bootstrap_clients.py` from Bash.

To refresh this tree from the repo root before publishing:

```bash
python3 scripts/sync_claude_plugin.py
```

Run from the **repository root** (parent of `scripts/`).
