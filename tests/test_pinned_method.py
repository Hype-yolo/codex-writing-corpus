import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import writing_context as context


class PinnedMethodTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.source = self.home / "plugins/cache/example/1/skills/example/SKILL.md"
        self.source.parent.mkdir(parents=True)
        self.method = "## Write and review\n\nSynthetic approved writing method.\n\n"
        self.source.write_text("## Retrieval\nSynthetic retrieval.\n" + self.method + "## Other\nOther content.\n")
        self.lock = self.home / "writing-methods/write-like-me/lock.json"
        self.cli = Path(context.__file__)
        self.env = {**os.environ, "CODEX_HOME": str(self.home)}

    def run_cli(self, *args, data=None):
        return subprocess.run([sys.executable, str(self.cli), *args],
                              input=json.dumps(data or {"samples": []}),
                              text=True, capture_output=True, env=self.env)

    def pin(self):
        return context.pin_official_method(self.source, self.lock,
                                          hashlib.sha256(self.method.encode()).hexdigest())

    def test_upstream_update_deletion_and_new_version_cannot_change_prompt(self):
        self.pin()
        before = self.run_cli()
        self.assertEqual(before.returncode, 0, before.stderr)
        newer = self.source.parents[3] / "2/skills/example/SKILL.md"
        newer.parent.mkdir(parents=True)
        newer.write_text("## Write and review\nDifferent new version.\n")
        self.source.write_text("## Write and review\nChanged in place.\n")
        self.assertEqual(self.run_cli().stdout, before.stdout)
        self.source.unlink()
        self.assertEqual(self.run_cli().stdout, before.stdout)
        self.assertEqual(self.run_cli("--method-only").stdout, self.method)
        self.assertEqual(json.loads(before.stdout)["method_lock_path"], str(self.lock.resolve()))

    def test_existing_pin_is_idempotent_but_never_replaced(self):
        meta = self.pin()
        before = self.lock.read_bytes()
        self.assertEqual(self.pin(), meta)
        self.assertEqual(self.lock.read_bytes(), before)
        self.source.write_text("## Write and review\nUnapproved update.\n")
        with self.assertRaisesRegex(ValueError, "already pinned"):
            context.pin_official_method(self.source, self.lock)
        self.assertEqual(self.lock.read_bytes(), before)
        self.assertEqual(context.load_pinned_method(self.lock)[0], self.method)

    def test_missing_pin_does_not_discover_installed_source(self):
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Pinned writing method missing", result.stderr)
        self.assertFalse(self.lock.exists())

    def test_corrupt_or_missing_snapshot_stops_both_render_modes(self):
        self.pin()
        lock = json.loads(self.lock.read_text())
        snapshot = self.lock.parent / lock["method_file"]
        snapshot.write_text(self.method + "unreviewed modification")
        for args in ((), ("--method-only",)):
            result = self.run_cli(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("checksum mismatch", result.stderr)
        snapshot.unlink()
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("snapshot missing", result.stderr)

    def test_install_checksum_rejects_wrong_version_without_creating_pin(self):
        with self.assertRaisesRegex(ValueError, "approved method checksum"):
            context.pin_official_method(self.source, self.lock, "0" * 64)
        self.assertFalse(self.lock.exists())

    def test_explicit_install_and_existing_reference_render_are_identical(self):
        result = self.run_cli("--pin-official-skill", str(self.source))
        self.assertEqual(result.returncode, 0, result.stderr)
        samples = [{"id": "example", "text": "Synthetic reference.", "tier": "explicit",
                    "authorship": {"status": "user_provided_not_verified"},
                    "sources": [{"path": "current_request"}]}]
        result = self.run_cli(data={"samples": samples})
        self.assertEqual(result.returncode, 0, result.stderr)
        before = context.render(self.source.read_text(), samples)
        after = json.loads(result.stdout)
        self.assertEqual(after["prompt"], before["prompt"])
        self.assertEqual(after["method_sha256"], before["method_sha256"])

    def test_old_runtime_source_flag_cannot_bypass_pin(self):
        self.pin()
        result = self.run_cli("--official-skill", str(self.source))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
