---
description: Generate Markdown subset release notes from a catalog index
argument-hint: "[index-image] [package-names]"
---

# Subset release notes

Use when the user gives an **index image** and **OLM package names**, or asks for partial or subset operator release notes. The tooling runs `opm render`, `oc image extract`, and reads **ClusterServiceVersion** manifests.

Work from this plugin’s root: the directory that contains `requirements.txt`, `bin/prega-release-notes`, and `scripts/` (when installed via a marketplace, use **`${CLAUDE_PLUGIN_ROOT}`** as `cd` target).

## 0. Ensure `oc` and `opm` exist

- Prefer `command -v oc` and `command -v opm` (or `oc version --client`).
- If either is missing, choose one path **before** running the main CLI:

  **A — Integrated auto-install (simplest)** — downloads official `oc`/`opm` into `<repo>/bin` from mirror.openshift.com when missing:

  ```bash
  cd "${CLAUDE_PLUGIN_ROOT}"
  export OCP_VERSION=4.20          # align with index major.minor / dev-preview tag
  ./bin/prega-release-notes --auto-install-clients --index "<INDEX>" -p "<PKG>" -o out.md
  ```

  Or set `PREG_RELEASE_NOTES_AUTO_INSTALL_CLIENTS=1` instead of the flag.

  **B — Bootstrap only** — then add `bin` to `PATH`:

  ```bash
  python3 scripts/bootstrap_clients.py
  export PATH="$PWD/bin:$PATH"
  ```

  **C — Full OpenShift Client Download** — for extra tools, checksum-first flows, or ambiguous versions: read and follow [openshift-client-download/SKILL.md](../skills/openshift-client-download/SKILL.md) (from [ai-helpers@b0e2950](https://github.com/midu16/ai-helpers/commit/b0e29501edb4722e6bdeae1ad67acab6a5483527)).

## 1. Python dependencies

If PyYAML may be missing: `pip install -r requirements.txt` in that directory.

## 2. Registry auth

Set `DOCKER_CONFIG` (directory with `config.json`) or `--authfile` when pulling from private registries.

## 3. Run the release-notes CLI

```bash
cd "${CLAUDE_PLUGIN_ROOT}"
./bin/prega-release-notes --index "<INDEX_IMAGE>" -p "<PKG1>" -p "<PKG2>" -o release-notes.md
```

4. Read the output file (or stdout if `-o` omitted) and present it; offer brief edits only if the user wants tone or structure changes—preserve versions and image references.

Arguments reference: `./bin/prega-release-notes --help`
