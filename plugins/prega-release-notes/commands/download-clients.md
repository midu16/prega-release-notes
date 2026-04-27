---
description: Download and install OpenShift CLIs from official sources
argument-hint: "[clients-and-versions]"
---

# Download clients

**Slash command:** `/download-clients` (from this plugin’s `commands/` directory; when installed as a plugin it may appear namespaced—see `/help`).

Interpret natural-language **which clients and versions** are needed, resolve **official** artifacts, verify integrity when the vendor publishes checksums, and install into a prefix the user approves (default: `prega-release-notes/bin/`). Aligns with [ai-helpers@b0e2950](https://github.com/midu16/ai-helpers/commit/b0e29501edb4722e6bdeae1ad67acab6a5483527).

**Load the skill first:** [openshift-client-download/SKILL.md](../skills/openshift-client-download/SKILL.md).

## Implementation

### 1. Ingest the user description

- Parse arguments for desired **tools**, **version constraints**, **OS/arch** hints, and **install location**.
- If critical information is missing, ask **one** focused question before large downloads.

### 2. Discover platform

```bash
uname -s
uname -m
```

Map to vendor naming (`amd64`/`arm64`) per the skill.

### 3. prega-release-notes fast path (oc + opm only)

When the user only needs **oc** and **opm** for catalog release notes on Linux or macOS:

```bash
cd "${CLAUDE_PLUGIN_ROOT}"
export OCP_VERSION=4.20   # or 4.22.0-ec.0 for dev-preview path
python3 scripts/bootstrap_clients.py
export PATH="$PWD/bin:$PATH"
oc version --client
opm version
```

For broader tools (Helm, ROSA, operator-sdk, checksum-first flows), follow the **OpenShift Client Download** skill step-by-step instead of relying on the bootstrap helper alone.

### 4. Stage, verify, install (full skill flow)

- Use a disposable staging directory under `.work/openshift-client-download/` unless the user specifies another path.
- `curl -fL` (or equivalent), verify SHA256 when the vendor ships `sha256sum.txt`.
- `chmod +x`, print `export PATH=...` and smoke commands.

### 5. Report outcomes

- Installed paths, PATH snippet, verification status, and anything skipped.

## Return value

Concise summary: versions, URLs or directories, checksum status, install paths, PATH updates, smoke-test results or errors.
