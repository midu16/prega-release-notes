---
name: subset-release-notes
description: >-
  Generates Markdown release notes for a user-specified list of OLM package
  names from a catalog index image using opm render, default-channel head bundles,
  and ClusterServiceVersion data extracted with oc image extract. Use when the
  user asks for subset or partial release notes, per-operator notes, or passes
  package names with an index image (e.g. quay.io/prega/prega-operator-index:tag).
---

# Subset release notes (catalog CLI)

This skill applies to the **prega-release-notes** repository layout: all commands below assume the working directory is the root of that repository (the folder containing `requirements.txt`, `bin/`, and `scripts/`).

## Prerequisites

- **PyYAML:** `pip install -r requirements.txt`
- **`oc`** (always for bundle extract) and **`opm`** (unless `--rendered-json` is used).
- Registry pull access: `DOCKER_CONFIG` (directory with `config.json`), `REGISTRY_AUTH_FILE`, or `--authfile`.

### When `oc` or `opm` is missing

1. **Fast path (this repo):** run `python3 scripts/bootstrap_clients.py` (or `./scripts/bootstrap_clients.py` if executable) after setting `OCP_VERSION` to match the index (e.g. `4.20` for `stable-4.20`, or `4.22.0-ec.0` for dev-preview). Binaries land in `<repo>/bin/`. Then:

   ```bash
   export PATH="/path/to/prega-release-notes/bin:$PATH"
   ```

2. **CLI integrated path:** pass `--auto-install-clients` (or set `PREG_RELEASE_NOTES_AUTO_INSTALL_CLIENTS=1`) so `release_notes_subset.py` runs `bootstrap_clients.py` automatically before resolving tools. Use `--ocp-version` (or env `OCP_VERSION`) to pick the mirror channel.

3. **Broader / manual installs** (Helm, ROSA, checksum-first flows, ambiguous versions): follow [.cursor/skills/openshift-client-download/SKILL.md](../openshift-client-download/SKILL.md), adapted from [ai-helpers@b0e2950](https://github.com/midu16/ai-helpers/commit/b0e29501edb4722e6bdeae1ad67acab6a5483527).

The CLI prefers `<repo>/bin/oc` and `<repo>/bin/opm` over unrelated binaries on `PATH` when both exist.

## Command

```bash
cd /path/to/prega-release-notes
export DOCKER_CONFIG=/path/to/dir_containing_config_json
pip install -r requirements.txt
chmod +x bin/prega-release-notes scripts/bootstrap_clients.py   # once (optional; can use python3 path)
./bin/prega-release-notes --auto-install-clients --ocp-version 4.20 \
  --index quay.io/prega/prega-operator-index:v4.22.0-ec.0 \
  --packages ocs-operator \
  --packages metallb-operator \
  -o subset-release-notes.md
```

Equivalent:

```bash
python3 scripts/release_notes_subset.py --auto-install-clients …
```

Comma-separated packages in one flag are allowed, for example `--packages ocs-operator,odf-operator`.

## Behavior

1. Runs `opm render <index> --output=json` (unless `--rendered-json` points at a saved NDJSON file for offline use).
2. For each requested **package** name, finds `olm.package` → `defaultChannel`, then the **latest** bundle entry on that channel (version order matches `sort -V`).
3. Resolves the `olm.bundle` **image** for that head bundle and runs `oc image extract … --path /manifests:.`.
4. Parses the first `*clusterserviceversion.yaml` under `manifests/` and emits Markdown (display name, version, container image, stripped description, related images).

Use `--opm-timeout 0` for an unlimited `opm render` wait (default is 7200 seconds).

## Output shape

The file starts with a title and short preamble, then one `##` section per successful package, then a **Skipped or failed packages** section if any package could not be resolved or extracted.

## Optional agent polish

After the script succeeds, the agent may tighten wording, group related operators, or align tone with team release-note style—without removing factual fields (versions, image references, package names).

## Offline / testing

```bash
cd /path/to/prega-release-notes
./bin/prega-release-notes \
  --rendered-json tests/fixtures/release_notes_subset/index.jsonl \
  -p operator-a \
  -o out.md
```

Still requires `oc` and registry access for a real bundle pull unless extraction is mocked; unit tests: `python3 -m unittest tests.test_release_notes_subset -v`.

## Using this repository as a standalone clone

Copy `.cursor/skills/subset-release-notes` (and optionally `openshift-client-download`) into another project’s `.cursor/skills/`, or open **prega-release-notes** as the Cursor workspace root so skills load automatically.

For **Claude Code**, copy `.claude/commands/subset-release-notes.md` and `.claude/commands/download-clients.md` into the target project’s `.claude/commands/`.
