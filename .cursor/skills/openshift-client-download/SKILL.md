---
name: openshift-client-download
description: >-
  OpenShift Client Download — select, verify, and install official CLI binaries
  (OpenShift oc/kubectl/openshift-install, ROSA, Helm, opm, operator-sdk, and common
  helpers) from user-described needs on Linux or macOS, using mirror and vendor sites
  with checksum verification when available. Use when installing or upgrading oc,
  opm, kubectl, or related CLIs for prega-release-notes or other OpenShift workflows.
---

# OpenShift Client Download

Upstream reference: [ai-helpers@b0e2950](https://github.com/midu16/ai-helpers/commit/b0e29501edb4722e6bdeae1ad67acab6a5483527) (`plugins/utils/skills/openshift-client-download`).

Use this skill when the user (or a slash command) asks to **download**, **install**, or **pin versions** of platform CLIs—especially OpenShift and cloud tooling—based on a **natural-language description** (for example: “oc and openshift-install for 4.16 on Linux arm64”, “latest stable ROSA CLI”, “helm 3 plus yq”).

## When to Use

- Interpreting vague or partial requirements into a concrete list of binaries and versions for **OpenShift Client Download** workflows.
- Choosing the correct **architecture** (`x86_64` / `amd64`, `aarch64` / `arm64`) and **OS** (Linux, macOS; Windows only if the user explicitly asks).
- Resolving **official download locations** and **integrity checks** (SHA sums, signatures) instead of unverified third-party mirrors.
- Explaining what was installed, where it landed, and how to put it on `PATH`.

## Prerequisites (agent checks)

- `curl` or `wget`, `tar`/`unzip` as needed, `sha256sum` or `shasum -a 256` for verification.
- Write access to an install prefix the user accepts (default suggestions: `./.local/bin`, `$HOME/.local/bin`, or a project-local `./bin`).
- Network access to vendor CDNs.

If something is missing, say what to install and offer a fallback (for example, package manager) only when the user wants it.

## Step 1 — Normalize the request

From the user’s description, extract:

1. **Which clients** (see mapping below; add more only from official sources).
2. **Version policy**: exact `X.Y.Z`, “latest z-stream for 4.Y”, “stable channel”, or “latest GA”—if ambiguous, ask one short clarifying question before downloading large artifacts.
3. **OS and arch**: prefer `uname -s` and `uname -m` (or the user’s stated platform). Map `aarch64` → `arm64`, `x86_64` → `amd64` where vendor filenames use the latter.

## Step 2 — Official artifacts (default catalog)

Use these **patterns**; **always** re-resolve the exact URL from the vendor page or directory listing when the user cares about a **specific patch**, because paths change frequently.

### OpenShift `oc`, `kubectl`, and often `openshift-install`

- **Index**: [OpenShift mirror clients](https://mirror.openshift.com/pub/openshift-v4/clients/ocp/) — browse the version directory (for example `4.16.20/`) for file names.
- **Typical files** (names vary slightly by release):
  - Linux x86_64: `openshift-client-linux-amd64-rhel9.tar.gz` (or `rhel8`), often `openshift-install-linux-*.tar.gz` in the same version folder for IPI/UPI installers.
  - Linux arm64: `openshift-client-linux-arm64-*.tar.gz`.
  - macOS: `openshift-client-mac.tar.gz` or `openshift-client-mac-arm64.tar.gz`.
- **Checksums**: Prefer `sha256sum.txt` or `SHA256SUM` in the **same** directory as the tarball; verify before extracting.

After extraction, common binaries: `oc`, `kubectl`; install may include `openshift-install`.

### ROSA CLI (`rosa`)

- Prefer **Red Hat customer downloads** or documented **GitHub releases** for `openshift/rosa` when the user wants OSS bits—pick one source per session and stay consistent with checksums offered there.

### Helm

- Official script or tarball: [Helm install](https://helm.sh/docs/intro/install/) — e.g. `get.helm.sh/helm-vX.Y.Z-linux-amd64.tar.gz` with published checksums.

### `opm` (Operator Package Manager)

- Often shipped alongside OCP client drops on the mirror in the same version directory; if absent, follow current OpenShift documentation for “Installing opm” rather than random binaries.

### `operator-sdk`

- [Operator SDK installation](https://sdk.operatorframework.io/docs/installation/) — use the documented release asset for the requested version and arch.

### Common helpers (when the user asks)

- **`yq`**, **`jq`**, **`grpcurl`**: use upstream release pages and verify published checksums or vendor package signatures when available.

## Step 3 — Download and verify

1. Create a working directory (for example `.work/openshift-client-download/<timestamp>/` in the repo, or a user-provided path outside git—**never** commit downloaded binaries).
2. Download each artifact with `curl -fL --retry 3 -O <url>` (or equivalent).
3. **Verify** using vendor-provided SHA256 (file or checksum line). If the vendor only provides SHA256 embedded in the release page, compare explicitly; if no checksum exists, state that limitation clearly.
4. Extract with `tar`/`unzip` into a `staging/` subfolder, then **copy only intended binaries** into the install prefix.
5. `chmod +x` on placed binaries.
6. Print **absolute paths**, suggested `export PATH=...`, and quick smoke tests (`oc version --client`, `kubectl version --client`, etc.).

## Step 4 — Safety and transparency

- Prefer **read-only** steps until the user confirms install location and version choices when disk or bandwidth is large (full openshift-install + clients).
- Never silently replace system packages; prefer user-writable prefixes.
- **prega-release-notes** bundles a non-interactive bootstrap: `scripts/bootstrap_clients.py` (Python; same mirror family as the prega `00_client_download.sh` script). Merge that artifact list with this catalog when automating `oc` + `opm` for release notes—do not invent private URLs.

## Return value

Summarize the **OpenShift Client Download** run:

- Resolved **clients**, **versions**, **URLs** (or mirror directories), **checksum status**, **install paths**, and **PATH** instructions.
- Any **skipped** items (unsupported OS, missing arch on mirror, ambiguous version) with the smallest next question to unblock.
