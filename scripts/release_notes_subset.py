#!/usr/bin/env python3
"""
Generate Markdown release notes for a subset of OLM packages from a catalog index.

Uses ``opm render`` on the index image, resolves the head bundle on each package's
default channel (``sort -V`` on channel entry names), extracts manifests from each
bundle image with ``oc image extract``, then emits Markdown from each
ClusterServiceVersion.

Requires: opm, oc (unless ``--rendered-json``), PyYAML (``requirements.txt``).
``opm render`` output may be NDJSON or formatted JSON (no ``jq -c`` step required).
``oc image extract`` uses ``/manifests:.`` and falls back to a full root extract
when that path yields no CSV.

Optional: ``--include-github-prs`` reads ``github.com`` repository hints from CSV
annotations and lists recent **merged** PRs via the GitHub API (set ``GITHUB_TOKEN``
or ``--github-token`` for higher rate limits). PRs are a heuristic aid—correlate
with bundle version and OCI image references in the notes.

Registry auth: set DOCKER_CONFIG (directory containing config.json) or pass
``--authfile``.

If ``oc``/``opm`` are missing, use ``--auto-install-clients`` (or set
``PREG_RELEASE_NOTES_AUTO_INSTALL_CLIENTS=1``) to run ``scripts/bootstrap_clients.py``
and install official clients into ``<repo>/bin`` from mirror.openshift.com
(``OCP_VERSION`` / ``--ocp-version`` selects the channel; see
``.cursor/skills/openshift-client-download/SKILL.md``).

Usage (from this repository root ``prega-release-notes/``):

  export DOCKER_CONFIG=/path/to/dir   # dir contains config.json
  pip install -r requirements.txt
  ./bin/prega-release-notes --auto-install-clients --ocp-version 4.20 \\
      --index quay.io/prega/prega-operator-index:tag \\
      --packages ocs-operator metallb-operator -o notes.md
"""

from __future__ import annotations

import argparse
import html.parser
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def resolve_tool(binary_name: str, user_value: str) -> str | None:
    """Resolve a CLI: explicit path, then <repo>/bin, then cwd/bin, then PATH."""
    u = user_value.strip()
    p = Path(u)
    if p.is_file():
        return str(p.resolve())
    bin_names = [binary_name]
    if sys.platform == "win32" and not binary_name.endswith(".exe"):
        bin_names.append(f"{binary_name}.exe")
    for base in (_REPO_ROOT, Path.cwd()):
        for bn in bin_names:
            cand = base / "bin" / bn
            if cand.is_file():
                return str(cand.resolve())
    w = shutil.which(u)
    if w:
        return w
    return None


_AUTO_INSTALL_ENV = "PREG_RELEASE_NOTES_AUTO_INSTALL_CLIENTS"


def auto_install_clients_requested(args: argparse.Namespace) -> bool:
    if getattr(args, "auto_install_clients", False):
        return True
    v = os.environ.get(_AUTO_INSTALL_ENV, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _load_bootstrap_clients_module(repo_root: Path):
    path = repo_root / "scripts" / "bootstrap_clients.py"
    spec = importlib.util.spec_from_file_location("_prega_bootstrap_clients", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load bootstrap module spec: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_bootstrap_clients(repo_root: Path, ocp_version: str) -> None:
    script = repo_root / "scripts" / "bootstrap_clients.py"
    if not script.is_file():
        raise SystemExit(f"Client bootstrap module not found: {script}")
    bin_dir = repo_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["OCP_VERSION"] = ocp_version
    env["PREG_RELEASE_NOTES_BIN_DIR"] = str(bin_dir)
    print(
        f"Installing oc/opm into {bin_dir} (OCP_VERSION={ocp_version}) …",
        flush=True,
    )
    mod = _load_bootstrap_clients_module(repo_root)
    rc = int(
        mod.run_bootstrap(
            repo_root=repo_root,
            ocp_version=ocp_version,
            bin_dir=bin_dir,
        )
    )
    if rc != 0:
        raise SystemExit(
            f"scripts/bootstrap_clients.py failed with exit code {rc}"
        )


def maybe_bootstrap_missing_clients(
    args: argparse.Namespace,
    *,
    need_opm: bool,
) -> None:
    if not auto_install_clients_requested(args):
        return
    oc_ok = resolve_tool("oc", args.oc) is not None
    opm_ok = True
    if need_opm:
        opm_ok = resolve_tool("opm", args.opm) is not None
    if oc_ok and opm_ok:
        return
    run_bootstrap_clients(_REPO_ROOT, args.ocp_version)


def load_ndjson(text: str) -> list[dict[str, Any]]:
    """
    Parse catalog output from ``opm render`` or a saved file.

    Accepts:

    - **NDJSON** — one JSON object per line (legacy ``opm`` output).
    - **Single JSON document** — a JSON array of objects, or one object
      (including pretty-printed multi-line).
    - **Leading noise** — log or progress lines before the first ``{``/``[``
      (some ``opm`` builds write to stdout before the catalog stream).

    Trailing non-JSON text after the last value is ignored when at least one
    object was parsed.
    """
    s = text.strip()
    if s.startswith("\ufeff"):
        s = s.lstrip("\ufeff").lstrip()
    if not s:
        return []

    start = -1
    for i, ch in enumerate(s):
        if ch in "{[":
            start = i
            break
    if start < 0:
        return []

    buf = s[start:]
    dec = json.JSONDecoder()
    out: list[dict[str, Any]] = []
    idx = 0
    n = len(buf)
    while idx < n:
        while idx < n and buf[idx] in " \t\r\n":
            idx += 1
        if idx >= n:
            break
        try:
            obj, end = dec.raw_decode(buf, idx)
        except json.JSONDecodeError as e:
            if out:
                break
            raise SystemExit(
                "Could not parse catalog JSON from opm render (or --rendered-json file). "
                f"First error: {e.msg} at line {e.lineno}, column {e.colno}. "
                "If this is not catalog output, check opm version and index image."
            ) from e
        idx = end
        if isinstance(obj, dict):
            out.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    out.append(item)
    return out


def sort_version_sort(names: list[str]) -> list[str]:
    """Order bundle entry names like GNU ``sort -V``."""
    if not names:
        return []
    proc = subprocess.run(
        ["sort", "-V"],
        input="\n".join(names) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return sorted(names)
    return [ln for ln in proc.stdout.splitlines() if ln]


def channel_entry_names(entries: Any) -> list[str]:
    """Collect bundle names from olm.channel ``entries`` (strings or objects)."""
    if not isinstance(entries, list):
        return []
    names: list[str] = []
    for e in entries:
        if isinstance(e, str):
            names.append(e)
        elif isinstance(e, dict) and "name" in e:
            names.append(str(e["name"]))
    return names


def resolve_package_to_bundle_image(
    objs: list[dict[str, Any]], package: str
) -> tuple[str | None, str | None]:
    """
    Return (bundle_image_ref, error_message).
    bundle_image_ref is None on failure.
    """
    default_channel: str | None = None
    for o in objs:
        if o.get("schema") == "olm.package" and o.get("name") == package:
            default_channel = o.get("defaultChannel")
            if isinstance(default_channel, str):
                break
            return None, f"package {package!r}: missing or invalid defaultChannel"
    if not default_channel:
        return None, f"package {package!r}: not found in index"

    head_bundle: str | None = None
    for o in objs:
        if o.get("schema") != "olm.channel":
            continue
        if o.get("package") != package or o.get("name") != default_channel:
            continue
        names = channel_entry_names(o.get("entries"))
        if not names:
            return None, f"package {package!r}: channel {default_channel!r} has no entries"
        sorted_names = sort_version_sort(names)
        head_bundle = sorted_names[-1]
        break

    if not head_bundle:
        return None, f"package {package!r}: channel {default_channel!r} not found"

    for o in objs:
        if o.get("schema") == "olm.bundle" and o.get("name") == head_bundle:
            img = o.get("image")
            if isinstance(img, str) and img:
                return img, None
            return None, f"bundle {head_bundle!r}: missing image field"

    return None, f"bundle {head_bundle!r}: olm.bundle not found in index"


def run_opm_render(
    index_image: str,
    opm_bin: str,
    *,
    timeout_sec: float | None,
) -> str:
    cmd = [opm_bin, "render", index_image, "--output=json"]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"opm render timed out after {int(timeout_sec or 0)}s; use --opm-timeout 0 for no limit"
        ) from None
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[-8000:]
        print(err, file=sys.stderr)
        raise SystemExit(f"opm render failed with exit code {proc.returncode}")
    return proc.stdout


class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def strip_html_description(raw: str | None, max_len: int = 8000) -> str:
    if not raw:
        return ""
    s = raw.strip()
    if "<" not in s and ">" not in s:
        return s[:max_len]
    p = _HTMLStripper()
    try:
        p.feed(s)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", "", s)[:max_len]
    text = re.sub(r"\s+", " ", p.get_text()).strip()
    return text[:max_len]


def find_csv_path(manifests_root: Path) -> Path | None:
    for p in manifests_root.rglob("*.clusterserviceversion.yaml"):
        return p
    for p in manifests_root.rglob("*clusterserviceversion.yaml"):
        return p
    return None


def parse_csv(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise SystemExit(
            f"PyYAML is required: pip install -r {_REPO_ROOT / 'requirements.txt'}"
        )
    with path.open(encoding="utf-8", errors="replace") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return data


_GITHUB_REPO_URL_RE = re.compile(
    r"https://github\.com/([\w.-]+)/([\w.-]+)(?:/[\w./-]*)?",
    re.IGNORECASE,
)


def extract_github_repo_urls(text: str) -> list[str]:
    """Return unique canonical `https://github.com/owner/repo` URLs found in text."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _GITHUB_REPO_URL_RE.finditer(text):
        owner, repo = m.group(1), m.group(2)
        url = f"https://github.com/{owner}/{repo}"
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def repository_urls_from_csv(csv_doc: dict[str, Any]) -> list[str]:
    """Discover operator source repo URLs (GitHub) from CSV metadata annotations."""
    ordered: list[str] = []
    seen: set[str] = set()
    meta = csv_doc.get("metadata")
    if not isinstance(meta, dict):
        return ordered
    ann = meta.get("annotations")
    if not isinstance(ann, dict):
        return ordered
    priority_keys = (
        "repository",
        "operators.operatorframework.io/repository",
        "operators.operatorframework.io/source",
        "source",
    )
    for key in priority_keys:
        val = ann.get(key)
        if isinstance(val, str):
            for u in extract_github_repo_urls(val):
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
    for key, val in ann.items():
        if key in priority_keys:
            continue
        if isinstance(val, str) and "github.com" in val.lower():
            for u in extract_github_repo_urls(val):
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
    return ordered


def github_owner_repo(url: str) -> tuple[str, str] | None:
    m = re.match(
        r"https://github\.com/([\w.-]+)/([\w.-]+)/?", url.rstrip("/"), re.IGNORECASE
    )
    if m:
        return m.group(1), m.group(2)
    return None


# Issue keys like OCPBUGS-83413; exclude common false positives (SHA-256, RFC-2119, …).
_JIRA_KEY_INLINE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]{1,14}-\d{1,9})\b",
)
_JIRA_IN_URL = re.compile(
    r"(?:redhat\.atlassian\.net|issues\.redhat\.com)/browse/"
    r"([A-Za-z][A-Za-z0-9]{1,14}-\d{1,9})\b",
    re.IGNORECASE,
)
_JIRA_PROJECT_BLOCKLIST = frozenset(
    {
        "SHA",
        "RFC",
        "ISO",
        "UTF",
        "CVE",
        "CPU",
        "GPU",
        "PDF",
        "TLS",
        "SSL",
        "NPM",
        "API",
    }
)


def _jira_project_part(key: str) -> str:
    parts = key.upper().rsplit("-", 1)
    return parts[0] if parts else ""


def extract_jira_keys(text: str) -> list[str]:
    """
    Collect Jira / issue keys (e.g. ``OCPBUGS-83413``, ``OADP-7868``) from free text
    or existing ``…/browse/KEY`` URLs. Output keys are uppercased and de-duplicated
    (stable order: URL-derived keys first, then inline matches).
    """
    if not text:
        return []
    seen: set[str] = set()
    keys: list[str] = []

    def add(raw: str) -> None:
        k = raw.strip().upper()
        if not k or k in seen:
            return
        proj = _jira_project_part(k)
        if proj in _JIRA_PROJECT_BLOCKLIST:
            return
        if len(proj) < 2:
            return
        seen.add(k)
        keys.append(k)

    for m in _JIRA_IN_URL.finditer(text):
        add(m.group(1))
    for m in _JIRA_KEY_INLINE.finditer(text):
        add(m.group(1))
    return keys


def redhat_jira_browse_url(key: str) -> str:
    """Canonical Red Hat Jira browse URL for ``KEY`` (e.g. ``OCPBUGS-83413``)."""
    safe = urllib.parse.quote(key.upper(), safe="")
    return f"https://redhat.atlassian.net/browse/{safe}"


def jira_keys_markdown_list(keys: list[str]) -> str:
    """One markdown bullet per key with ``redhat.atlassian.net`` browse links."""
    if not keys:
        return "- *(No Jira-style keys detected in PR titles or bodies.)*\n"
    lines = []
    for k in keys:
        url = redhat_jira_browse_url(k)
        lines.append(f"- [{k}]({url})")
    return "\n".join(lines) + "\n"


def pr_change_summary(title: str, body: str | None, *, max_chars: int = 400) -> str:
    """
    Short plain-text summary for release notes: prefer first paragraph of the PR
    body, else the title. Collapses whitespace and strips HTML-ish fragments lightly.
    """
    t = (title or "").strip()
    b = (body or "").strip()
    if b:
        # Strip markdown code fences / leading comment blocks
        b = re.sub(r"^<!--.*?-->", "", b, flags=re.DOTALL).strip()
        para = re.split(r"\n\s*\n", b, maxsplit=1)[0]
        para = re.sub(r"[\r\n]+", " ", para).strip()
        para = re.sub(r"\s+", " ", para)
        if len(para) > 8:
            text = para
        else:
            text = t or para
    else:
        text = t
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text or t or "(no description)"


def fetch_github_merged_pulls(
    owner: str,
    repo: str,
    *,
    limit: int,
    token: str | None,
    timeout: float = 45.0,
) -> list[dict[str, Any]]:
    """
    Return newest merged PRs (GitHub ``/pulls`` API), newest ``merged_at`` first.

    Unauthenticated requests are rate-limited; set ``GITHUB_TOKEN`` or pass a token.
    """
    own = urllib.parse.quote(owner, safe="")
    rep = urllib.parse.quote(repo, safe="")
    per = min(100, max(limit * 3, limit + 10))
    api = (
        f"https://api.github.com/repos/{own}/{rep}/pulls"
        f"?state=closed&per_page={per}&sort=updated&direction=desc"
    )
    req = urllib.request.Request(
        api,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "prega-release-notes",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"GitHub API HTTP {e.code} for {owner}/{repo}: {detail}") from e
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    merged: list[dict[str, Any]] = [
        pr for pr in data if isinstance(pr, dict) and pr.get("merged_at")
    ]
    merged.sort(key=lambda pr: str(pr.get("merged_at") or ""), reverse=True)
    return merged[:limit]


def github_prs_markdown(
    repo_urls: list[str],
    *,
    pr_limit: int,
    token: str | None,
    bundle_version: str,
    container_image: str,
) -> str:
    """Markdown fragment: source repo + optional merged PR table."""
    lines: list[str] = []
    if not repo_urls:
        return ""
    lines.append("### Source repository")
    lines.append("")
    for u in repo_urls:
        parsed = github_owner_repo(u)
        if parsed:
            o, r = parsed
            lines.append(f"- [{o}/{r}]({u})")
        else:
            lines.append(f"- `{u}`")
    lines.append("")
    lines.append(
        "Use the bundle **version** and **container / related images** above when "
        "mapping GitHub work to this OLM bundle; image digests and tags are the "
        "authoritative package identifiers."
    )
    if pr_limit <= 0:
        return "\n".join(lines) + "\n"
    primary = repo_urls[0]
    gr = github_owner_repo(primary)
    if not gr:
        lines.append("")
        lines.append("*(Skipping GitHub PR list: primary repository URL is not GitHub.)*")
        return "\n".join(lines) + "\n"
    owner, repo = gr
    lines.append("")
    lines.append("### Recent merged pull requests")
    lines.append("")
    lines.append(
        f"Latest **{pr_limit}** merged PRs from `{owner}/{repo}` (newest merge first). "
        "This list is **heuristic**: correlate with this bundle using version strings, "
        f"bundle version `{bundle_version or '?'}`, image references "
        f"(e.g. `{container_image[:80]}…` if truncated), and your release process."
    )
    lines.append("")
    try:
        pulls = fetch_github_merged_pulls(
            owner, repo, limit=pr_limit, token=token
        )
    except OSError as e:
        lines.append(f"*(Could not reach GitHub: {e})*")
        return "\n".join(lines) + "\n"
    except RuntimeError as e:
        lines.append(f"*(GitHub API: {e})*")
        return "\n".join(lines) + "\n"
    if not pulls:
        lines.append("*(No merged PRs returned for this query.)*")
        return "\n".join(lines) + "\n"

    aggregate_jira: list[str] = []
    aggregate_seen: set[str] = set()

    for pr in pulls:
        num = pr.get("number")
        title = str(pr.get("title", "") or "")
        raw_body = pr.get("body")
        body: str | None
        if raw_body is None:
            body = None
        elif isinstance(raw_body, str):
            body = raw_body
        else:
            body = str(raw_body)
        html_url = str(pr.get("html_url", "") or "")
        merged = str(pr.get("merged_at", "") or "")[:19]

        combined = f"{title}\n{body or ''}"
        jkeys = extract_jira_keys(combined)
        for k in jkeys:
            if k not in aggregate_seen:
                aggregate_seen.add(k)
                aggregate_jira.append(k)

        summary = pr_change_summary(title, body)
        title_one = re.sub(r"[\r\n]+", " ", title).strip()
        title_one = re.sub(r"\s+", " ", title_one)
        if len(title_one) > 200:
            title_one = title_one[:197] + "…"

        if num is not None and html_url:
            lines.append(f"#### PR [#{num}]({html_url})")
        else:
            lines.append("#### PR")
        lines.append("")
        lines.append(f"- **Title:** {title_one}")
        lines.append(f"- **Merged (UTC):** `{merged}`")
        lines.append(f"- **Change:** {summary}")
        if jkeys:
            jira_line = ", ".join(
                f"[{k}]({redhat_jira_browse_url(k)})" for k in jkeys
            )
            lines.append(f"- **Jira / references:** {jira_line}")
        else:
            lines.append(
                "- **Jira / references:** *(none detected in PR title or body; "
                "check the PR on GitHub for subtickets.)*"
            )
        lines.append("")

    lines.append("#### Jira keys referenced above (deduplicated)")
    lines.append("")
    lines.append(jira_keys_markdown_list(aggregate_jira).rstrip("\n"))
    lines.append("")
    return "\n".join(lines)


def related_images_summary(csv: dict[str, Any], max_list: int = 20) -> str:
    spec = csv.get("spec")
    if not isinstance(spec, dict):
        return ""
    rel = spec.get("relatedImages")
    if not isinstance(rel, list) or not rel:
        return ""
    n = len(rel)
    lines = [f"- **Related images:** {n} entries"]
    for i, item in enumerate(rel[:max_list]):
        if isinstance(item, dict):
            name = item.get("name", "")
            image = item.get("image", "")
            lines.append(f"  - `{name}` → `{image}`")
        else:
            lines.append(f"  - `{item}`")
    if n > max_list:
        lines.append(f"  - … and {n - max_list} more")
    return "\n".join(lines)


def markdown_for_package(
    package: str,
    csv_doc: dict[str, Any],
    *,
    github_pr_limit: int = 0,
    github_token: str | None = None,
) -> str:
    meta = csv_doc.get("metadata")
    meta_name = ""
    if isinstance(meta, dict):
        meta_name = str(meta.get("name", ""))

    spec = csv_doc.get("spec")
    display = version = desc = container = ""
    if isinstance(spec, dict):
        display = str(spec.get("displayName", "") or "")
        version = str(spec.get("version", "") or "")
        desc = strip_html_description(spec.get("description"))
        container = str(spec.get("containerImage", "") or "")

    ann = {}
    if isinstance(meta, dict) and isinstance(meta.get("annotations"), dict):
        ann = meta["annotations"]
    if not container and isinstance(ann, dict):
        container = str(ann.get("containerImage", "") or "")

    lines = [
        f"## {display or package}",
        "",
        f"- **Package:** `{package}`",
        f"- **CSV:** `{meta_name}`",
        f"- **Version:** `{version}`",
    ]
    if container:
        lines.append(f"- **Container image:** `{container}`")
    lines.append("")
    if desc:
        lines.append("### Description")
        lines.append("")
        lines.append(desc)
        lines.append("")
    rel = related_images_summary(csv_doc)
    if rel:
        lines.append(rel)
        lines.append("")

    repos = repository_urls_from_csv(csv_doc)
    if repos:
        lines.append(
            github_prs_markdown(
                repos,
                pr_limit=github_pr_limit,
                token=github_token,
                bundle_version=version,
                container_image=container,
            )
        )
    elif github_pr_limit > 0:
        lines.append("### Source repository")
        lines.append("")
        lines.append(
            "*(No `github.com` repository URL was found in CSV metadata annotations; "
            "cannot list merged PRs. Add e.g. `repository` to the CSV or pass bundle-only notes.)*"
        )
        lines.append("")
    return "\n".join(lines)


def _oc_image_extract_run(
    bundle_image: str,
    cwd: Path,
    oc_bin: str,
    registry_config: str | None,
    path_spec: str,
) -> tuple[int, str]:
    cmd = [oc_bin, "image", "extract"]
    if registry_config:
        cmd.append(f"--registry-config={registry_config}")
    cmd.extend([bundle_image, "--path", path_spec, "--confirm"])
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    err = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, err


def oc_extract_manifests(
    bundle_image: str,
    dest: Path,
    oc_bin: str,
    registry_config: str | None,
) -> None:
    """
    Extract bundle manifests for CSV discovery.

    Tries ``/manifests:.`` first (FBC layout). Some ``oc``/bundle combinations
    return an empty tree for that path; then extracts the **image root** with
    ``/:.`` and searches for a ClusterServiceVersion under the extract tree.
    """
    dest.mkdir(parents=True, exist_ok=True)

    def has_csv(tree: Path) -> bool:
        return find_csv_path(tree) is not None

    mdir = dest / "manifests"
    if mdir.exists():
        shutil.rmtree(mdir, ignore_errors=True)

    rc1, err1 = _oc_image_extract_run(
        bundle_image, dest, oc_bin, registry_config, "/manifests:."
    )
    primary_ok = rc1 == 0 and mdir.is_dir() and any(mdir.iterdir()) and has_csv(dest)
    if primary_ok:
        return

    first_ctx = f"rc={rc1}" if rc1 != 0 else "no usable CSV under manifests/"
    if mdir.exists():
        shutil.rmtree(mdir, ignore_errors=True)

    root = dest / "_image_root"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    rc2, err2 = _oc_image_extract_run(
        bundle_image, root, oc_bin, registry_config, "/:."
    )
    if rc2 != 0:
        tail = (err2 or err1)[-4000:]
        raise RuntimeError(
            f"oc image extract failed for {bundle_image!r}: "
            f"/manifests:. ({first_ctx}); full root /:. rc={rc2}: {tail}"
        )
    if not has_csv(root):
        raise RuntimeError(
            f"oc image extract for {bundle_image!r}: full image root contained no "
            f"ClusterServiceVersion YAML. Primary stderr (truncated): "
            f"{err1[-2000:]!r}"
        )


def authfile_from_env() -> str | None:
    explicit = os.environ.get("REGISTRY_AUTH_FILE")
    if explicit and Path(explicit).is_file():
        return explicit
    dc = os.environ.get("DOCKER_CONFIG")
    if not dc:
        return None
    p = Path(dc)
    if p.is_file():
        return str(p)
    cand = p / "config.json"
    if cand.is_file():
        return str(cand)
    return None


def generate_from_rendered(
    objs: list[dict[str, Any]],
    packages: list[str],
    oc_bin: str,
    registry_config: str | None,
    *,
    github_pr_limit: int = 0,
    github_token: str | None = None,
) -> str:
    sections: list[str] = [
        "# Subset release notes",
        "",
        "Generated from catalog bundle ClusterServiceVersion manifests.",
        "Catalog JSON accepts NDJSON or formatted JSON from ``opm render``; bundle "
        "extract uses ``/manifests:.`` and falls back to a full image root extract "
        "when needed.",
        "",
    ]
    missing: list[str] = []
    for pkg in packages:
        img, err = resolve_package_to_bundle_image(objs, pkg)
        if err or not img:
            missing.append(f"- `{pkg}`: {err or 'unknown error'}")
            continue
        with tempfile.TemporaryDirectory(prefix=f"bundle-{pkg}-") as tmp:
            tpath = Path(tmp)
            try:
                oc_extract_manifests(img, tpath, oc_bin, registry_config)
            except RuntimeError as e:
                missing.append(f"- `{pkg}`: {e}")
                continue
            csv_path = find_csv_path(tpath)
            if not csv_path:
                missing.append(
                    f"- `{pkg}`: no ClusterServiceVersion YAML after bundle extract"
                )
                continue
            csv_doc = parse_csv(csv_path)
            sections.append(
                markdown_for_package(
                    pkg,
                    csv_doc,
                    github_pr_limit=github_pr_limit,
                    github_token=github_token,
                )
            )
            sections.append("---")
            sections.append("")

    if missing:
        sections.append("## Skipped or failed packages")
        sections.append("")
        sections.extend(missing)
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Markdown release notes for selected OLM packages from a catalog index.",
    )
    parser.add_argument(
        "--index",
        help="Catalog index image (required unless --rendered-json is set; unused with --rendered-json)",
    )
    parser.add_argument(
        "--packages",
        "-p",
        action="append",
        default=[],
        help="OLM package name (repeatable; comma-separated values allowed per flag)",
    )
    parser.add_argument("-o", "--output", help="Write Markdown to this file (default: stdout)")
    parser.add_argument("--opm", default="opm", help="opm binary (default: opm)")
    parser.add_argument("--oc", default="oc", help="oc binary (default: oc)")
    parser.add_argument(
        "--opm-timeout",
        type=float,
        default=7200.0,
        help="Seconds for opm render (default: 7200; use 0 for no limit)",
    )
    parser.add_argument(
        "--authfile",
        help="Registry auth file (config.json). Default: REGISTRY_AUTH_FILE or DOCKER_CONFIG/config.json",
    )
    parser.add_argument(
        "--rendered-json",
        help="Skip opm: load catalog from this NDJSON file (testing / offline)",
    )
    parser.add_argument(
        "--include-github-prs",
        action="store_true",
        help=(
            "Append source GitHub repo (from CSV annotations) and recent merged PRs "
            "(requires network; use GITHUB_TOKEN or --github-token for higher rate limits)"
        ),
    )
    parser.add_argument(
        "--github-pr-limit",
        type=int,
        default=20,
        metavar="N",
        help="Max merged PRs per operator repo when --include-github-prs (default: 20)",
    )
    parser.add_argument(
        "--github-token",
        help="GitHub API token (default: env GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--auto-install-clients",
        action="store_true",
        help=(
            "If oc or opm is missing, run scripts/bootstrap_clients.py to install "
            "official clients into <repo>/bin (mirror.openshift.com). "
            f"Also enabled when {_AUTO_INSTALL_ENV}=1."
        ),
    )
    parser.add_argument(
        "--ocp-version",
        default=os.environ.get("OCP_VERSION", "4.20"),
        metavar="VER",
        help="OCP version/channel for bootstrap_clients.py (default: env OCP_VERSION or 4.20)",
    )
    args = parser.parse_args(argv)

    if yaml is None:
        req = _REPO_ROOT / "requirements.txt"
        print(
            f"Error: PyYAML is not installed. Run: pip install -r {req}",
            file=sys.stderr,
        )
        return 1

    raw_packages: list[str] = []
    for group in args.packages:
        for part in re.split(r"[,\s]+", group.strip()):
            if part:
                raw_packages.append(part)
    if not raw_packages:
        print("Error: pass at least one package via --packages / -p", file=sys.stderr)
        return 1

    packages = list(dict.fromkeys(raw_packages))

    maybe_bootstrap_missing_clients(args, need_opm=not bool(args.rendered_json))

    oc_bin = resolve_tool("oc", args.oc)
    if not oc_bin:
        print(
            "Error: oc not found; install OpenShift client, pass --oc, run "
            "scripts/bootstrap_clients.py, or retry with --auto-install-clients",
            file=sys.stderr,
        )
        return 1

    authfile = args.authfile or authfile_from_env()

    if args.rendered_json:
        path = Path(args.rendered_json)
        text = path.read_text(encoding="utf-8")
        objs = load_ndjson(text)
    else:
        if not args.index:
            print("Error: --index is required when not using --rendered-json", file=sys.stderr)
            return 1
        opm_bin = resolve_tool("opm", args.opm)
        if not opm_bin:
            print(
                "Error: opm not found; install opm, pass --opm, run "
                "scripts/bootstrap_clients.py, or retry with --auto-install-clients",
                file=sys.stderr,
            )
            return 1
        timeout = None if args.opm_timeout == 0 else args.opm_timeout
        text = run_opm_render(args.index, opm_bin, timeout_sec=timeout)
        objs = load_ndjson(text)

    gh_limit = args.github_pr_limit if args.include_github_prs else 0
    gh_tok = (args.github_token or os.environ.get("GITHUB_TOKEN") or "").strip() or None

    md = generate_from_rendered(
        objs,
        packages,
        oc_bin,
        authfile,
        github_pr_limit=gh_limit,
        github_token=gh_tok,
    )
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
