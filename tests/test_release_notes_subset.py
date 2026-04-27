"""Unit tests for scripts/release_notes_subset.py (no opm/oc/registry)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "release_notes_subset.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "release_notes_subset"


def _load_script():
    spec = importlib.util.spec_from_file_location("release_notes_subset", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release_notes_subset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rns = _load_script()


@unittest.skipUnless(rns.yaml is not None, "PyYAML required: pip install -r requirements.txt")
class ReleaseNotesSubsetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index_text = (FIXTURES / "index.jsonl").read_text(encoding="utf-8")
        self.objs = rns.load_ndjson(self.index_text)

    def test_resolve_head_bundle_image(self) -> None:
        img, err = rns.resolve_package_to_bundle_image(self.objs, "operator-a")
        self.assertIsNone(err)
        self.assertEqual(
            img,
            "quay.io/example/operator-a-bundle@sha256:1111111111111111111111111111111111111111111111111111111111111111",
        )

    def test_resolve_operator_b(self) -> None:
        img, err = rns.resolve_package_to_bundle_image(self.objs, "operator-b")
        self.assertIsNone(err)
        self.assertIn("operator-b-bundle", img or "")

    def test_resolve_missing_package(self) -> None:
        img, err = rns.resolve_package_to_bundle_image(self.objs, "no-such-pkg")
        self.assertIsNone(img)
        self.assertIn("not found", (err or "").lower())

    def test_load_ndjson_accepts_leading_log_line(self) -> None:
        nosy = (
            'time="2024-01-01T00:00:00Z" level=warning msg="registry"\n' + self.index_text
        )
        objs = rns.load_ndjson(nosy)
        self.assertEqual(len(objs), len(self.objs))

    def test_load_ndjson_pretty_json_array(self) -> None:
        pretty = json.dumps(self.objs, indent=2)
        roundtrip = rns.load_ndjson(pretty)
        self.assertEqual(len(roundtrip), len(self.objs))

    def test_extract_github_repo_urls(self) -> None:
        text = (
            "Upstream https://github.com/openshift/lvms-operator/blob/main/README.md "
            "and duplicate https://github.com/openshift/lvms-operator/issues/1"
        )
        urls = rns.extract_github_repo_urls(text)
        self.assertEqual(urls, ["https://github.com/openshift/lvms-operator"])

    def test_repository_urls_from_csv(self) -> None:
        doc = {
            "metadata": {
                "annotations": {
                    "repository": "https://github.com/foo/bar-operator",
                    "other": "ignored",
                }
            }
        }
        self.assertEqual(
            rns.repository_urls_from_csv(doc),
            ["https://github.com/foo/bar-operator"],
        )

    def test_github_owner_repo(self) -> None:
        self.assertEqual(
            rns.github_owner_repo("https://github.com/a/b"),
            ("a", "b"),
        )
        self.assertIsNone(rns.github_owner_repo("https://example.com/x"))

    def test_oc_extract_fallback_full_image_root(self) -> None:
        yaml_content = (
            "apiVersion: operators.coreos.com/v1alpha1\n"
            "kind: ClusterServiceVersion\n"
            "metadata:\n  name: z.v1\n"
            "spec:\n  displayName: Z\n  version: '1'\n"
        )

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            cwd = Path(str(kwargs.get("cwd") or "."))
            joined = " ".join(cmd)
            if "/manifests:." in joined:
                m = cwd / "manifests"
                m.mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if "/:." in joined:
                m = cwd / "manifests"
                m.mkdir(parents=True, exist_ok=True)
                (m / "z.clusterserviceversion.yaml").write_text(
                    yaml_content, encoding="utf-8"
                )
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(f"unexpected oc invocation: {cmd}")

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            with mock.patch.object(rns.subprocess, "run", side_effect=fake_run):
                rns.oc_extract_manifests("quay.io/x/bundle:v1", dest, "oc", None)
            self.assertIsNotNone(rns.find_csv_path(dest))

    def test_github_prs_markdown_with_mock_fetch(self) -> None:
        sample = [
            {
                "number": 42,
                "title": "Add feature for OADP-7868",
                "body": (
                    "First paragraph explains the change in detail for reviewers.\n\n"
                    "Second section.\n\n"
                    "See also https://redhat.atlassian.net/browse/OCPBUGS-83413"
                ),
                "merged_at": "2024-06-01T12:00:00Z",
                "html_url": "https://github.com/o/r/pull/42",
            }
        ]

        class _Resp:
            def read(self) -> bytes:
                return json.dumps(sample).encode("utf-8")

        class _CM:
            def __enter__(self) -> _Resp:
                return _Resp()

            def __exit__(self, *args: object) -> None:
                return None

        with mock.patch.object(rns.urllib.request, "urlopen", return_value=_CM()):
            md = rns.github_prs_markdown(
                ["https://github.com/o/r"],
                pr_limit=5,
                token=None,
                bundle_version="1.0.0",
                container_image="quay.io/x/y@sha256:abc",
            )
        self.assertIn("Source repository", md)
        self.assertIn("Recent merged pull requests", md)
        self.assertIn("PR [#42]", md)
        self.assertIn("Add feature for OADP-7868", md)
        self.assertIn("**Change:**", md)
        self.assertIn("First paragraph explains", md)
        self.assertIn(
            "https://redhat.atlassian.net/browse/OADP-7868", md
        )
        self.assertIn(
            "https://redhat.atlassian.net/browse/OCPBUGS-83413", md
        )
        self.assertIn("Jira keys referenced above", md)

    def test_extract_jira_keys_from_text_and_urls(self) -> None:
        text = (
            "Fix OCPBUGS-83618 and link https://redhat.atlassian.net/browse/OCPBUGS-83413 "
            "dup OCPBUGS-83413"
        )
        keys = rns.extract_jira_keys(text)
        self.assertEqual(keys, ["OCPBUGS-83413", "OCPBUGS-83618"])

    def test_extract_jira_keys_excludes_sha(self) -> None:
        self.assertEqual(rns.extract_jira_keys("hash sha-256 digest"), [])

    def test_pr_change_summary_prefers_body(self) -> None:
        s = rns.pr_change_summary(
            "title",
            "First para has enough chars to be used as the summary text here.\n\nMore.",
        )
        self.assertIn("First para", s)
        self.assertNotIn("More.", s)

    def test_strip_html_description(self) -> None:
        raw = "<p>One <em>two</em> three</p>"
        out = rns.strip_html_description(raw)
        self.assertIn("One", out)
        self.assertNotIn("<p>", out)

    def test_markdown_for_package(self) -> None:
        csv_path = FIXTURES / "operator-a-manifests" / "manifests" / "operator-a.clusterserviceversion.yaml"
        doc = rns.parse_csv(csv_path)
        md = rns.markdown_for_package("operator-a", doc)
        self.assertIn("Operator A Display", md)
        self.assertIn("1.1.0", md)
        self.assertIn("operator-a", md)
        self.assertIn("Release", md)
        self.assertNotIn("<strong>", md)
        self.assertIn("Related images", md)

    def test_generate_from_rendered_mock_extract(self) -> None:
        src_manifests = FIXTURES / "operator-a-manifests" / "manifests"

        def fake_extract(bundle_image: str, dest: Path, oc_bin: str, registry: str | None) -> None:
            shutil.copytree(src_manifests, dest / "manifests")

        with mock.patch.object(rns, "oc_extract_manifests", side_effect=fake_extract):
            md = rns.generate_from_rendered(self.objs, ["operator-a"], "oc-fake", None)

        self.assertIn("# Subset release notes", md)
        self.assertIn("Operator A Display", md)
        self.assertNotIn("Skipped or failed", md)

    def test_generate_unknown_package_lists_skip(self) -> None:
        with mock.patch.object(rns, "oc_extract_manifests"):
            md = rns.generate_from_rendered(self.objs, ["unknown-pkg"], "oc", None)
        self.assertIn("Skipped or failed", md)
        self.assertIn("unknown-pkg", md)


if __name__ == "__main__":
    unittest.main()
