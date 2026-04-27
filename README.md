# prega-release-notes

Standalone tooling to generate **Markdown release notes for a subset of OLM packages** from a single catalog index image: `opm render` → resolve head bundles on the default channel → `oc image extract` → read `ClusterServiceVersion` manifests. The CLI accepts **NDJSON or formatted JSON** from `opm` (no `jq` pipeline). If `oc image extract --path /manifests:.` yields no CSV, it **retries with a full image root** extract and discovers the CSV under the tree. Optional **`--include-github-prs`** adds the operator’s GitHub repo (from CSV annotations) and recent **merged** PRs for manual correlation with bundle version and OCI image lines.

## Demo video

[![prega-release-notes — demo walkthrough (YouTube)](https://img.youtube.com/vi/ibwXh71U-TQ/hqdefault.jpg)](https://www.youtube.com/watch?v=ibwXh71U-TQ)

**[▶ Watch on YouTube](https://www.youtube.com/watch?v=ibwXh71U-TQ)** — GitHub’s README renderer does not support embedded iframes or autoplay; the image above is a standard **click-to-play** thumbnail that opens the video on YouTube (where playback and autoplay follow YouTube’s own rules).

## Setup

```bash
cd prega-release-notes   # this directory
pip install -r requirements.txt
chmod +x bin/prega-release-notes scripts/bootstrap_clients.py
```

### OpenShift clients (`oc`, `opm`)

- **Already on your machine:** ensure they are on `PATH`, or place them under `bin/`.
- **Auto-download (official mirror):** either run `python3 scripts/bootstrap_clients.py` (or `./scripts/bootstrap_clients.py` if executable) with `OCP_VERSION` matching your index (e.g. `4.20` or `4.22.0-ec.0` for dev-preview), **or** pass **`--auto-install-clients`** to `./bin/prega-release-notes` so missing `oc`/`opm` are installed into `bin/` before the run. Optional: `PREG_RELEASE_NOTES_AUTO_INSTALL_CLIENTS=1`. Tune the channel with **`--ocp-version`** or env **`OCP_VERSION`**.

Broader installs (Helm, ROSA, checksum-first workflows) are documented in [.cursor/skills/openshift-client-download/SKILL.md](.cursor/skills/openshift-client-download/SKILL.md), aligned with [ai-helpers@b0e2950](https://github.com/midu16/ai-helpers/commit/b0e29501edb4722e6bdeae1ad67acab6a5483527).

Downloaded CLIs under `bin/` are listed in `.gitignore` (keep `bin/prega-release-notes` in git).

### Registry auth

`DOCKER_CONFIG` (directory containing `config.json`), `REGISTRY_AUTH_FILE`, or `--authfile`.

## Usage

```bash
export DOCKER_CONFIG=/path/to/auth-dir
export PATH="$PWD/bin:$PATH"   # if using bootstrap / --auto-install-clients
./bin/prega-release-notes --auto-install-clients --ocp-version 4.20 \
  --index quay.io/prega/prega-operator-index:v4.22.0-ec.0 \
  --packages ocs-operator metallb-operator \
  -o subset-release-notes.md
```

See `./bin/prega-release-notes --help` for `--opm-timeout`, `--rendered-json`, and other options.

### GitHub merged PRs (optional)

- **`--include-github-prs`** — fetch recent merged PRs for the first `github.com` repo URL found in CSV metadata (common keys: `repository`, `operators.operatorframework.io/repository`, `source`, or any annotation value containing `github.com`).
- **`--github-pr-limit N`** — default 20; only applies with `--include-github-prs`.
- **`GITHUB_TOKEN`** or **`--github-token`** — recommended for API rate limits and private forks.

PR lists are **heuristic** (newest merges first); tie them to the shipped bundle using **CSV version**, **containerImage**, and **relatedImages** in the same section of the generated notes.

For each merged PR, the tool adds a short **Change** line (first paragraph of the PR body when present) and **Jira / references** lines: keys like `OCPBUGS-83413` or `https://redhat.atlassian.net/browse/…` / `issues.redhat.com/browse/…` in the title or body are turned into canonical links `https://redhat.atlassian.net/browse/<KEY>`, plus a deduplicated list at the end of the PR section.

## Tests

```bash
pip install -r requirements.txt
python3 -m unittest tests.test_release_notes_subset -v
```

## Claude Code marketplace (install via `/plugin`)

This repo ships a **plugin marketplace** at [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) (see [Claude Code: Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)).

1. Add the marketplace (GitHub shorthand; uses the default branch):
   ```bash
   claude plugin marketplace add midu16/prega-release-notes
   ```
   Or in the Claude Code UI: register the Git repo so the checkout contains **`.claude-plugin/marketplace.json`** at the repository root (that path is what Claude resolves; the earlier “marketplace file not found” error means that file was missing or the URL pointed at the wrong tree).

2. Install the plugin (marketplace name **`midu16-prega`**):
   ```bash
   claude plugin install prega-release-notes@midu16-prega
   ```

3. In sessions, run Bash/CLI steps from **`${CLAUDE_PLUGIN_ROOT}`** (plugin install root with `bin/`, `scripts/`, and `requirements.txt`).

After changing root `.claude/commands` or `.cursor/skills`, refresh the vendored plugin tree before committing:

```bash
python3 scripts/sync_claude_plugin.py
```

## Cursor skills and Claude commands

| Purpose | Path |
|--------|------|
| Subset release notes | `.cursor/skills/subset-release-notes/SKILL.md` |
| OpenShift client download (full catalog) | `.cursor/skills/openshift-client-download/SKILL.md` |
| Slash: subset notes | `.claude/commands/subset-release-notes.md` |
| Slash: download clients | `.claude/commands/download-clients.md` |
| Marketplace catalog | `.claude-plugin/marketplace.json` |
| Plugin payload (synced) | `plugins/prega-release-notes/` |

Copy into another repo’s `.cursor/skills/` and `.claude/commands/`, or open **prega-release-notes** as the workspace root.

Slash command YAML can include an optional `allowed-tools` field (see [Claude Code command frontmatter](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/command-development/references/frontmatter-reference.md)) if you want a tighter tool sandbox for a given environment; the copies in this repo omit it so `Bash` steps (`pip`, `oc`, `opm`, bootstrap scripts, etc.) are not blocked by an incomplete filter list.

The portable CLI is **`bin/prega-release-notes`** (wrapper around `scripts/release_notes_subset.py`).
