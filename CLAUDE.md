# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**prega-release-notes** generates Markdown release notes for a subset of OLM (Operator Lifecycle Manager) packages from a catalog index image. The workflow: `opm render` → resolve head bundles on default channels → `oc image extract` → parse ClusterServiceVersion manifests → emit Markdown.

## Common Commands

### Running the tool

```bash
# Basic usage (assumes oc/opm on PATH and DOCKER_CONFIG set)
./bin/prega-release-notes \
  --index quay.io/prega/prega-operator-index:v4.22.0-ec.0 \
  --packages ocs-operator metallb-operator \
  -o subset-release-notes.md

# Auto-install missing oc/opm from mirror.openshift.com
./bin/prega-release-notes --auto-install-clients --ocp-version 4.20 \
  --index <index-image> \
  --packages <pkg1>,<pkg2> \
  -o notes.md

# Direct Python invocation (equivalent to bin wrapper)
python3 scripts/release_notes_subset.py <args>

# Offline mode using cached catalog JSON
./bin/prega-release-notes \
  --rendered-json tests/fixtures/release_notes_subset/index.jsonl \
  -p operator-a -o out.md
```

### Testing

```bash
# Run all unit tests
python3 -m unittest tests.test_release_notes_subset -v

# Tests use fixtures in tests/fixtures/release_notes_subset/ and mock oc_extract_manifests
```

### Bootstrap OpenShift clients

```bash
# Manual bootstrap (download oc and opm into bin/)
OCP_VERSION=4.20 python3 scripts/bootstrap_clients.py

# Or let the CLI auto-install when --auto-install-clients is passed
```

### Claude Code marketplace

- **Catalog:** [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) (marketplace id: `midu16-prega`)
- **Plugin directory:** [`plugins/prega-release-notes/`](plugins/prega-release-notes/) — vendored copy of commands, skills, `scripts/`, `bin/`, `requirements.txt`
- **Refresh after edits:** `python3 scripts/sync_claude_plugin.py`
- **User install:** `claude plugin marketplace add midu16/prega-release-notes` then `claude plugin install prega-release-notes@midu16-prega` ([docs](https://code.claude.com/docs/en/plugin-marketplaces))

## Architecture

### Core modules

- **bin/prega-release-notes**: Bash wrapper that invokes the Python script
- **scripts/release_notes_subset.py**: Main implementation (540 lines)
  - `resolve_tool()`: Finds binaries in `<repo>/bin`, `cwd/bin`, then PATH
  - `run_opm_render()`: Executes `opm render <index> --output=json` with timeout
  - `resolve_package_to_bundle_image()`: Finds `olm.package` → `defaultChannel` → head bundle via `sort -V`
  - `oc_extract_manifests()`: Runs `oc image extract` for bundle `/manifests`
  - `parse_csv()`: Loads ClusterServiceVersion YAML with PyYAML
  - `markdown_for_package()`: Emits release note section (display name, version, description, related images)
  - `generate_from_rendered()`: Orchestrates full workflow for all packages
- **scripts/bootstrap_clients.py**: Native Python bootstrap; downloads official oc/opm from mirror.openshift.com (stdlib + tarfile; no curl)
- **tests/test_release_notes_subset.py**: Unit tests using fixtures and mocks

### Data flow

1. **Render catalog**: `opm render <index>` → NDJSON stream of `olm.package`, `olm.channel`, `olm.bundle` objects
2. **Resolve bundles**: For each package, find `defaultChannel`, collect channel `entries`, sort with `sort -V`, take last (head)
3. **Extract manifests**: `oc image extract <bundle-image> --path /manifests:.` into temp directory
4. **Parse CSV**: Find `*.clusterserviceversion.yaml`, parse with PyYAML
5. **Emit Markdown**: Extract `spec.displayName`, `spec.version`, `spec.description` (HTML-stripped), `spec.containerImage`, `spec.relatedImages`

### Key behaviors

- **Tool resolution**: Prefers `<repo>/bin/oc` and `<repo>/bin/opm` over system PATH to keep repo self-contained
- **Auto-install**: When `--auto-install-clients` (or env `PREG_RELEASE_NOTES_AUTO_INSTALL_CLIENTS=1`), missing oc/opm trigger `scripts/bootstrap_clients.py` via `importlib` (no bash subprocess)
- **Version sorting**: Bundle entries use GNU `sort -V` to determine head (falls back to Python `sorted()` if unavailable)
- **Registry auth**: Reads `REGISTRY_AUTH_FILE` or `DOCKER_CONFIG/config.json` unless `--authfile` is passed
- **HTML stripping**: CSV descriptions may contain HTML; `strip_html_description()` uses `html.parser.HTMLParser` with fallback regex
- **Timeout**: `opm render` defaults to 7200s; use `--opm-timeout 0` for unlimited
- **Error handling**: Missing packages or extraction failures appear in "Skipped or failed packages" section

## Development Notes

- **Dependencies**: Only PyYAML (see requirements.txt); oc and opm are external binaries
- **Downloaded CLIs**: Listed in .gitignore except `bin/prega-release-notes` (keep tracked)
- **OCP version mapping**: `--ocp-version` supports `4.20` (stable) or `4.22.0-ec.0` (dev-preview) for `bootstrap_clients.py`
- **Skills/commands**: Available for Cursor (`.cursor/skills/`) and Claude Code (`.claude/commands/`) — copy to other repos or open this repo as workspace root

## Registry Access (User Requirement)

**IMPORTANT**: Registry authentication must be provided by the user. Do not attempt to create, modify, or configure registry credentials.

The tool requires authenticated pull access to bundle images. The user must ensure one of:
- `export DOCKER_CONFIG=/path/to/dir` (directory containing config.json)
- `export REGISTRY_AUTH_FILE=/path/to/config.json`
- Pass `--authfile /path/to/config.json`

If registry authentication is missing, inform the user that they need to configure it according to their registry provider's documentation (e.g., `podman login`, `docker login`).
