#!/usr/bin/env python3
"""
Download official ``oc`` / ``kubectl`` and ``opm`` into ``PREG_RELEASE_NOTES_BIN_DIR``
(default: ``<repo>/bin``). Mirror layout matches the former ``bootstrap_clients.sh`` and
prega ``00_client_download.sh`` (OpenShift mirror clients).

Environment (same as the shell script):

- ``PREG_RELEASE_NOTES_BIN_DIR`` — install directory (default: ``<repo>/bin``)
- ``OCP_VERSION`` — e.g. ``4.20`` or ``4.22.0-ec.0`` for dev-preview
- ``OCP_BASE_URL`` — override mirror base (default includes ``x86_64/clients`` path)

Requires: Python 3.9+, ``curl`` is **not** required (uses :mod:`urllib`).
Requires: ``tar`` is **not** required for ``oc`` / ``kubectl`` (uses :mod:`tarfile`).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent

_DEFAULT_BASE = "https://mirror.openshift.com/pub/openshift-v4/x86_64/clients"


def _repo_root(explicit: Path | None) -> Path:
    return explicit.resolve() if explicit else _REPO_ROOT


def _detect_rhel_suffix() -> str:
    """Return ``rhel8`` or ``rhel9`` for Linux client tarball names (shell parity)."""
    if sys.platform != "linux":
        return "rhel9"
    os_release = Path("/etc/os-release")
    try:
        text = os_release.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "rhel9"
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            kv[k.strip()] = v.strip().strip('"')
    id_ = kv.get("ID", "")
    id_like = kv.get("ID_LIKE", "")
    vid = kv.get("VERSION_ID", "9")
    maj_s = vid.split(".", 1)[0]
    maj = int(maj_s) if maj_s.isdigit() else 9

    if id_ == "fedora":
        return "rhel9" if maj >= 38 else "rhel8"
    if id_ == "rhel" or "rhel" in id_like or "fedora" in id_like:
        return "rhel8" if maj <= 8 else "rhel9"
    return "rhel9"


def _machine_arch() -> str:
    m = os.uname().machine
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    print(f"Unsupported architecture: {m}", file=sys.stderr)
    sys.exit(1)


def _os_kind() -> str:
    s = os.uname().sysname
    if s == "Linux":
        return "linux"
    if s == "Darwin":
        return "mac"
    print(f"Unsupported OS: {s} (Linux and macOS supported)", file=sys.stderr)
    sys.exit(1)


def _ocp_url_path(ocp_version: str) -> str:
    if re.search(r"-ec\.\d+$", ocp_version):
        return f"ocp-dev-preview/{ocp_version}"
    return f"ocp/stable-{ocp_version}"


def _download(url: str, dest: Path, timeout: float = 600.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "prega-release-notes-bootstrap/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            chunk = 256 * 1024
            with dest.open("wb") as f:
                while True:
                    b = resp.read(chunk)
                    if not b:
                        break
                    f.write(b)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading {url}") from e


def _find_named_executable(root: Path, name: str) -> Path | None:
    for p in root.rglob(name):
        if p.is_file() and p.name == name:
            return p
    return None


def _tar_extractall(tf: tarfile.TarFile, path: Path) -> None:
    if sys.version_info >= (3, 12):
        tf.extractall(path, filter="data")
    else:
        tf.extractall(path)


def _chmod_exec(p: Path) -> None:
    mode = p.stat().st_mode
    p.chmod(mode | 0o111)


def _extract_oc_kubectl(archive: Path, bin_dir: Path, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    extract_root = work / "oc_extract"
    if extract_root.exists():
        shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        _tar_extractall(tf, extract_root)
    for name in ("oc", "kubectl"):
        found = _find_named_executable(extract_root, name)
        if found:
            dest = bin_dir / name
            shutil.copy2(found, dest)
            _chmod_exec(dest)


def _download_oc(
    bin_dir: Path,
    download_dir: Path,
    ocp_base_url: str,
    ocp_url_path: str,
    arch: str,
    os_kind: str,
    rhel_suffix: str,
) -> None:
    if os_kind == "linux":
        url = (
            f"{ocp_base_url}/{ocp_url_path}/"
            f"openshift-client-linux-{arch}-{rhel_suffix}.tar.gz"
        )
    elif arch == "arm64":
        url = f"{ocp_base_url}/{ocp_url_path}/openshift-client-mac-arm64.tar.gz"
    else:
        url = f"{ocp_base_url}/{ocp_url_path}/openshift-client-mac.tar.gz"

    temp_file = download_dir / "openshift-client.tar.gz"
    print(f"Downloading oc from {url}", flush=True)
    _download(url, temp_file)
    try:
        _extract_oc_kubectl(temp_file, bin_dir, download_dir)
    finally:
        temp_file.unlink(missing_ok=True)
    oc_bin = bin_dir / "oc"
    if not oc_bin.is_file():
        raise RuntimeError(f"oc not found in archive after extract: {url}")
    _chmod_exec(oc_bin)
    print(f"Installed: {oc_bin}", flush=True)


def _download_opm(
    bin_dir: Path,
    download_dir: Path,
    ocp_base_url: str,
    ocp_url_path: str,
    arch: str,
    os_kind: str,
    ocp_version: str,
    rhel_suffix: str,
) -> bool:
    base = f"{ocp_base_url}/{ocp_url_path}"
    temp_file = download_dir / "opm.tar.gz"
    urls: list[str] = []
    if os_kind == "linux":
        urls.append(f"{base}/opm-linux-{rhel_suffix}.tar.gz")
        urls.append(f"{base}/opm-linux-{ocp_version}.tar.gz")
    else:
        urls.append(f"{base}/opm-mac-{arch}.tar.gz")
        urls.append(f"{base}/opm-mac.tar.gz")

    extract_staging = download_dir / "opm_staging"

    for url in urls:
        print(f"Trying opm: {url}", flush=True)
        try:
            _download(url, temp_file)
        except RuntimeError:
            temp_file.unlink(missing_ok=True)
            continue

        if extract_staging.exists():
            shutil.rmtree(extract_staging, ignore_errors=True)
        extract_staging.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(temp_file, "r:gz") as tf:
                _tar_extractall(tf, extract_staging)
        except (tarfile.TarError, OSError) as e:
            print(f"opm extract failed: {e}", file=sys.stderr)
            temp_file.unlink(missing_ok=True)
            shutil.rmtree(extract_staging, ignore_errors=True)
            continue

        temp_file.unlink(missing_ok=True)

        candidates = [
            extract_staging / "opm",
            extract_staging / f"opm-{rhel_suffix}",
            extract_staging / "opm-rhel9",
            extract_staging / "opm-rhel8",
        ]
        opm_src: Path | None = None
        for c in candidates:
            if c.is_file():
                opm_src = c
                break
        if opm_src is None:
            found = _find_named_executable(extract_staging, "opm")
            opm_src = found

        if opm_src is None:
            shutil.rmtree(extract_staging, ignore_errors=True)
            continue

        dest = bin_dir / "opm"
        shutil.move(str(opm_src), str(dest))
        _chmod_exec(dest)
        shutil.rmtree(extract_staging, ignore_errors=True)
        for p in download_dir.glob("opm-*"):
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
        print(f"Installed: {dest}", flush=True)
        return True

    print(
        "Warning: could not download opm for "
        f"{os_kind}/{arch}; install manually (see .cursor/skills/openshift-client-download/SKILL.md)",
        file=sys.stderr,
    )
    return False


def run_bootstrap(
    *,
    repo_root: Path | None = None,
    ocp_version: str | None = None,
    bin_dir: Path | str | None = None,
) -> int:
    """
    Download ``oc`` / ``kubectl`` / ``opm`` into the repo bin directory.

    Returns ``0`` if ``oc`` is present at end; ``1`` if ``oc`` could not be installed.
    ``opm`` failure only prints a warning (same as the shell script).

    ``bin_dir`` defaults to ``PREG_RELEASE_NOTES_BIN_DIR`` or ``<repo_root>/bin``.
    """
    root = _repo_root(repo_root)
    if bin_dir is not None:
        bin_dir = Path(bin_dir).resolve()
    else:
        bin_dir = Path(
            os.environ.get("PREG_RELEASE_NOTES_BIN_DIR", str(root / "bin"))
        ).resolve()
    download_dir = bin_dir / "downloads"
    ocp_ver = (ocp_version or os.environ.get("OCP_VERSION", "4.20")).strip()
    ocp_base = os.environ.get("OCP_BASE_URL", _DEFAULT_BASE).rstrip("/")

    bin_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)

    arch = _machine_arch()
    os_kind = _os_kind()
    rhel_suffix = _detect_rhel_suffix()
    url_path = _ocp_url_path(ocp_ver)

    oc_path = bin_dir / "oc"
    if oc_path.is_file() and os.access(oc_path, os.X_OK):
        print(f"Using existing {oc_path}", flush=True)
    else:
        try:
            _download_oc(
                bin_dir, download_dir, ocp_base, url_path, arch, os_kind, rhel_suffix
            )
        except (RuntimeError, OSError, tarfile.TarError) as e:
            print(f"Error: {e}", file=sys.stderr)
            shutil.rmtree(download_dir, ignore_errors=True)
            return 1

    opm_path = bin_dir / "opm"
    if opm_path.is_file() and os.access(opm_path, os.X_OK):
        print(f"Using existing {opm_path}", flush=True)
    else:
        _download_opm(
            bin_dir,
            download_dir,
            ocp_base,
            url_path,
            arch,
            os_kind,
            ocp_ver,
            rhel_suffix,
        )

    shutil.rmtree(download_dir, ignore_errors=True)
    print(
        f'Bootstrap done. Add to PATH for this repo: export PATH="{bin_dir}:$PATH"',
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download official oc/kubectl and opm into the repo bin directory.",
    )
    parser.add_argument(
        "--ocp-version",
        metavar="VER",
        help="OCP version (default: env OCP_VERSION or 4.20); e.g. 4.22.0-ec.0 for dev-preview",
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        help="Install directory (default: env PREG_RELEASE_NOTES_BIN_DIR or <repo>/bin)",
    )
    args = parser.parse_args(argv)
    return run_bootstrap(
        ocp_version=args.ocp_version,
        bin_dir=args.bin_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
