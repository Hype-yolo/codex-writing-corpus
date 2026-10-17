import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import external_corpus as external
import writing_context


class ExternalCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.original = self.root / "original.jsonl"
        self.original.write_text('{"text":"synthetic fixture"}\n')

    def tearDown(self):
        self.temp.cleanup()

    def sample(self, number=0):
        return {"id": f"wechat-{number}", "text": f"Synthetic reviewed expression {number}",
                "tier": "auto_high_confidence", "authorship": {"status": "inferred_not_verified"},
                "reference_eligible": True,
                "review": {"status": "accepted", "method": "agent_review", "reason": "Synthetic test fixture"},
                "sources": [{"kind": "wechat", "path": str(self.original), "line": 1,
                             "conversation_id": f"conversation-{number}", "timestamp": "2026-01-01T00:00:00Z"}]}

    def enable(self, samples):
        path = self.out / "reviewed.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in samples), encoding="utf-8")
        manifest = {"schema_version": 1, "sources": [{"name": "fixture", "enabled": True,
                    "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
        (self.out / "external-sources.json").write_text(json.dumps(manifest))
        return path

    def test_absent_and_disabled_manifest_preserve_legacy_behavior(self):
        samples, stats = external.load_external_sources(self.out)
        self.assertEqual(samples, [])
        self.assertEqual(stats["external_sources_enabled"], 0)
        (self.out / "external-sources.json").write_text(json.dumps({"schema_version": 1, "sources": [{"enabled": False}]}))
        self.assertEqual(external.load_external_sources(self.out)[0], [])

    def test_modified_snapshot_fails_instead_of_becoming_references(self):
        path = self.enable([self.sample()])
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
            external.load_external_sources(self.out)

    def test_unreviewed_unknown_or_false_authorship_is_rejected(self):
        for change in (lambda s: s.pop("review"), lambda s: s["review"].update(status="pending"),
                       lambda s: s.update(tier="confirmed", authorship={"status": "human_confirmed"}),
                       lambda s: s["sources"][0].update(kind="unknown"),
                       lambda s: s["sources"][0].update(session_id="invented"),
                       lambda s: s["sources"][0].update(line=0),
                       lambda s: s.update(reference_eligible=False)):
            sample = self.sample()
            change(sample)
            self.enable([sample])
            with self.assertRaises(ValueError):
                external.load_external_sources(self.out)

    def test_pool_merges_sources_without_count_cap_and_writer_preserves_provenance(self):
        home = self.root / "home"
        sessions = home / "sessions"
        sessions.mkdir(parents=True)
        original_text = "我觉得学习新东西应该留点犯错的空间。我之前总想一次把流程做好，但是这样反而迟迟不开始。比如做一道菜，先把最基本的一步做出来，尝一尝哪里不合适，才有办法继续调整。因为每次动手都会有反馈，所以我更愿意从小的尝试开始。"
        events = [{"type": "session_meta", "payload": {"id": "conversation-0", "source": "app"}},
                  {"type": "response_item", "timestamp": "2026-01-01T00:00:00Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": original_text}]}}]
        (sessions / "fixture.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in events))
        samples = [self.sample(i) for i in range(6)]
        samples[1]["text"] = original_text
        samples[2]["text"] += "\u2028An in-string line separator"
        self.enable(samples)
        script = Path(__file__).resolve().parents[1] / "scripts" / "codex_corpus.py"
        result = subprocess.run([sys.executable, str(script), "select", "--codex-home", str(home),
                                 "--output-dir", str(self.out)], text=True, capture_output=True, check=True)
        result = json.loads(result.stdout)
        pool = result["samples"]
        self.assertEqual(len(pool), 6)
        self.assertEqual(result["stats"]["codex_eligible_before_exclusion"], 1)
        self.assertEqual(result["stats"]["external_samples_loaded"], 6)
        self.assertEqual(result["stats"]["duplicate_references_merged"], 1)
        duplicate = next(row for row in pool if row["text"] == original_text)
        self.assertEqual({s["kind"] for s in duplicate["sources"]}, {"codex", "wechat"})
        pack = writing_context.selection_prompt(pool)
        candidates = json.loads(pack["prompt"].split("\n", 1)[1])["candidates"]
        self.assertEqual(len(candidates), 6)
        self.assertIn("wechat", candidates[0]["source_kinds"])
        codex_origin_id = next(c["source_id"] for c in candidates if "codex" in c["source_kinds"])
        wechat_origin_id = next(c["source_id"] for c in candidates if c["text"] == samples[0]["text"])
        self.assertNotEqual(codex_origin_id, wechat_origin_id)
        chosen = writing_context.resolve_selection(pool, {"selected_ids": [f"R{i}" for i in range(1, 7)]})["samples"]
        method = "## Write and review\nKeep the supplied voice.\n"
        prompt = writing_context.render(method, chosen)["prompt"]
        self.assertTrue(prompt.startswith(method))
        rendered = json.loads(prompt.split("以下为参考数据。\n", 1)[1])
        self.assertEqual(len(rendered), 6)
        origin = next(s for row in rendered for s in row["sources"] if s.get("kind") == "wechat")
        self.assertEqual(origin["path"], str(self.original))
        self.assertEqual(origin["authorship"]["status"], "inferred_not_verified")
        self.assertNotIn("reviewed_snapshot", prompt)
        self.assertNotIn("Synthetic test fixture", prompt)
        self.assertNotIn('"review"', prompt)
        selected_origin = next(s for row in chosen for s in row["sources"] if s.get("kind") == "wechat")
        self.assertEqual(selected_origin["review"]["status"], "accepted")
        self.assertIn("sha256", selected_origin["reviewed_snapshot"])

    def test_same_body_confirmation_does_not_upgrade_wechat_origin(self):
        self.enable([self.sample()])
        loaded, _ = external.load_external_sources(self.out)
        confirmed = {"id": "codex-sample", "text": loaded[0]["text"], "tier": "confirmed",
                     "authorship": {"status": "human_confirmed"}, "sources": [{"kind": "codex",
                     "path": "fixture.jsonl", "line": 1, "session_id": "conversation-0"}]}
        merged = external.merge_same_text(loaded + [confirmed], lambda x: x)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["tier"], "confirmed")
        refs = writing_context.validate_samples(merged)
        wechat = next(s for s in refs[0]["sources"] if s.get("kind") == "wechat")
        self.assertEqual(wechat["authorship"]["status"], "inferred_not_verified")
        del next(s for s in merged[0]["sources"] if s.get("kind") == "wechat")["review"]
        with self.assertRaises(ValueError):
            writing_context.validate_samples(merged)

    def test_writer_rejects_false_human_confirmation_for_wechat_only(self):
        self.enable([self.sample()])
        loaded, _ = external.load_external_sources(self.out)
        loaded[0].update(tier="confirmed", authorship={"status": "human_confirmed"})
        with self.assertRaises(ValueError):
            writing_context.validate_samples(loaded)


if __name__ == "__main__":
    unittest.main()
