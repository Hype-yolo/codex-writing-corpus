import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'codex_corpus.py'
spec = importlib.util.spec_from_file_location('corpus', SCRIPT)
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)

EXPRESSION = '我觉得做一个东西之前，先想清楚自己究竟想解决什么问题特别重要。我之前总是看到别人做了新功能就跟着加，但是后来发现，多出来的按钮只会让人更加犹豫。对我来说，能够把一件小事讲明白，让别人真正用起来，比把所有功能都摆在首页更有意义。因为使用的人并不关心我写了多少代码，所以我更愿意把时间花在理解他们的困难上。'
OTHER = '我的看法是，学习新东西需要给自己留一点犯错的空间。我之前总想一次把流程做好，但是这样反而会迟迟不开始。比如学做一道菜，先把最基本的那一步做出来，尝一尝哪里不合适，才有办法继续调整。因为每次动手都会得到新的反馈，所以我现在更愿意从很小的尝试开始，慢慢摸清楚自己喜欢的节奏。'


def meta(sid='human', source='vscode'):
    return {'type': 'session_meta', 'payload': {'id': sid, 'source': source}}


def message(text, role='user', stamp='2026-10-02T00:00:00Z', **extra):
    return {'timestamp': stamp, 'type': 'response_item', 'payload': {'type': 'message', 'role': role, 'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}], **extra}}


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.output = self.root / 'out'
        self.output.mkdir()
        (self.home / 'sessions').mkdir(parents=True)
        (self.home / 'archived_sessions').mkdir()
        self.db = corpus.connect(self.output / 'index.sqlite3')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def file(self, name, records, archived=False):
        path = self.home / ('archived_sessions' if archived else 'sessions') / name
        path.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in records))
        return path

    def refresh(self):
        return corpus.refresh(self.db, self.output, self.home)

    def rows(self):
        return list(corpus.records(self.db, self.output))

    def test_default_codex_home_and_output_from_environment(self):
        env = dict(os.environ, CODEX_HOME=str(self.home))
        result = subprocess.run([sys.executable, str(SCRIPT), 'select', '--query', '测试'],
                                env=env, text=True, capture_output=True, check=True)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed['samples'], [])
        self.assertEqual(parsed['stats']['files_total'], 0)
        self.assertTrue((self.home / 'writing-corpus' / '语料索引.sqlite3').is_file())

    def test_unset_codex_home_falls_back_to_home(self):
        env = dict(os.environ, HOME=str(self.root / 'isolated-home'))
        env.pop('CODEX_HOME', None)
        result = subprocess.run([sys.executable, str(SCRIPT), 'refresh'],
                                env=env, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['files_total'], 0)
        self.assertTrue((self.root / 'isolated-home' / '.codex' / 'writing-corpus' / '统计.json').is_file())

    def test_input_override_does_not_move_default_output(self):
        env = dict(os.environ, CODEX_HOME=str(self.root / 'configured-home'))
        self.file('a.jsonl', [meta(), message(EXPRESSION)])
        subprocess.run([sys.executable, str(SCRIPT), 'refresh', '--codex-home', str(self.home)],
                       env=env, text=True, capture_output=True, check=True)
        self.assertTrue((self.root / 'configured-home' / 'writing-corpus' / '统计.json').is_file())
        self.assertFalse((self.home / 'writing-corpus').exists())

    def test_canonical_dedup_and_sources(self):
        self.file('one.jsonl', [meta('one'), message(EXPRESSION), {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': EXPRESSION}}, message(EXPRESSION)])
        self.file('two.jsonl', [meta('two'), message(EXPRESSION)], True)
        stats = self.refresh()
        self.assertEqual(stats['canonical_user_messages'], 3)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.rows()[0]['sources']), 3)
        self.assertEqual(self.rows()[0]['tier'], 'auto_high_confidence')
        self.assertEqual(self.rows()[0]['authorship']['status'], 'inferred_not_verified')

    def test_subagent_any_meta_excluded(self):
        self.file('agent.jsonl', [meta('agent', {'subagent': {'thread_spawn': {'parent_thread_id': 'root'}}}), meta('root'), message(EXPRESSION)])
        self.assertEqual(self.refresh()['files_excluded_subagents'], 1)
        self.assertEqual(self.rows(), [])
        self.file('late_agent.jsonl', [meta('root'), message(EXPRESSION), meta('agent', {'subagent': {'other': 'guardian'}})])
        self.refresh()
        self.assertEqual(self.rows(), [])

    def test_my_request_with_environment_and_offsets(self):
        mixed = '# AGENTS.md instructions\n<INSTRUCTIONS>不要提取这里</INSTRUCTIONS>\n<environment_context>机器信息</environment_context>\n## My request for Codex:\n' + EXPRESSION
        self.file('one.jsonl', [meta(), message(mixed)])
        self.refresh()
        row = self.rows()[0]
        self.assertEqual(row['text'], EXPRESSION)
        source = row['sources'][0]
        self.assertEqual(mixed[source['start']:source['end']], EXPRESSION)
        self.assertEqual(source['line'], 2)

    def test_my_request_does_not_swallow_real_prefix(self):
        value = OTHER + '\n\nMy request:\n' + EXPRESSION
        self.file('one.jsonl', [meta(), message(value)])
        self.refresh()
        self.assertEqual({r['text'] for r in self.rows()}, {OTHER, EXPRESSION})

    def test_structured_reply_and_metadata(self):
        self.file('one.jsonl', [meta(), message('<send_user_message_question_reply><answer>选择1</answer></send_user_message_question_reply>'), message(EXPRESSION, internal_chat_message_metadata_passthrough={'content_item_kinds': ['skills.selected_skill_instructions']}), message('<environment_context>machine</environment_context>')])
        self.refresh()
        self.assertEqual(self.rows(), [])

    def test_quoted_and_cross_session_assistant_copy(self):
        self.file('a.jsonl', [meta('a'), message(EXPRESSION, 'assistant', '2026-10-01T00:00:00Z')])
        self.file('b.jsonl', [meta('b'), message(EXPRESSION), message('这是别人写的内容：\n\n' + OTHER)])
        self.refresh()
        rows = self.rows()
        self.assertTrue(all(r['tier'] == 'review' for r in rows))
        row = next(r for r in rows if r['text'] == EXPRESSION)
        self.assertIn('matches_prior_assistant_output_global_fingerprint', row['reasons'])
        self.assertEqual(corpus.select(self.db, self.output, '', '', 3, ''), [])

    def test_assistant_echo_later_is_not_reverse_evidence(self):
        self.file('a.jsonl', [meta(), message(EXPRESSION, stamp='2026-10-01T00:00:00Z'), message(EXPRESSION, 'assistant', '2026-10-02T00:00:00Z')])
        self.refresh()
        self.assertEqual(self.rows()[0]['tier'], 'auto_high_confidence')

    def test_ai_tool_thread_prompt(self):
        tool = {'type': 'response_item', 'timestamp': '2026-10-01T00:00:00Z', 'payload': {'type': 'function_call', 'name': 'mcp__codex_app__create_thread', 'arguments': json.dumps({'prompt': EXPRESSION})}}
        self.file('a.jsonl', [meta('a'), tool])
        self.file('b.jsonl', [meta('b'), message(EXPRESSION)])
        self.refresh()
        self.assertEqual(self.rows()[0]['tier'], 'review')

    def test_subagent_assistant_output_is_fingerprinted(self):
        self.file('a.jsonl', [meta('agent', {'subagent': {'other': 'review'}}), message(EXPRESSION, 'assistant', '2026-10-01T00:00:00Z')])
        self.file('b.jsonl', [meta('human'), message(EXPRESSION)])
        self.refresh()
        self.assertEqual(self.rows()[0]['tier'], 'review')

    def test_tool_output_is_not_human_authorship(self):
        tool = {'type': 'response_item', 'timestamp': '2026-10-01T00:00:00Z', 'payload': {'type': 'function_call_output', 'output': EXPRESSION}}
        self.file('a.jsonl', [meta(), tool, message(EXPRESSION)])
        self.refresh()
        self.assertEqual(self.rows()[0]['tier'], 'review')

    def test_bearer_sensitive_never_persisted(self):
        value = EXPRESSION + '\nAuthorization: Bearer SYNTHETIC_AUDIT_CREDENTIAL_NOT_REAL_123456'
        self.file('a.jsonl', [meta(), message(value)])
        self.refresh()
        self.assertEqual(self.rows()[0]['tier'], 'excluded')
        self.assertNotIn('SYNTHETIC_AUDIT', self.db.execute('SELECT text FROM snippets').fetchone()[0])
        self.assertNotIn('SYNTHETIC_AUDIT', (self.output / '待确认片段.jsonl').read_text())

    def test_same_size_and_larger_rewrite_resets(self):
        path = self.file('a.jsonl', [meta(), message(EXPRESSION)])
        self.refresh()
        replacement = EXPRESSION.replace('我觉得', '我认为')
        self.file('a.jsonl', [meta(), message(replacement)])
        self.refresh()
        self.assertEqual([r['text'] for r in self.rows()], [replacement])
        self.file('a.jsonl', [meta(), message(OTHER), message(replacement)])
        self.refresh()
        self.assertEqual({r['text'] for r in self.rows()}, {OTHER, replacement})

    def test_reject_accept_and_sensitive_redaction(self):
        self.file('a.jsonl', [meta(), message(EXPRESSION), message(OTHER + '\n密码: synthetic-secret-123')])
        self.refresh()
        rows = self.rows()
        self.assertNotIn('synthetic-secret', '\n'.join(r['text'] for r in rows))
        self.assertNotIn('synthetic-secret', (self.output / '待确认片段.jsonl').read_text())
        sid = corpus.digest(EXPRESSION)
        (self.output / 'decisions.json').write_text(json.dumps({sid: 'reject'}))
        self.refresh()
        self.assertEqual(corpus.select(self.db, self.output, '', '', 3, ''), [])
        (self.output / 'decisions.json').write_text(json.dumps({'decisions': {sid: {'decision': 'accept'}}}))
        self.refresh()
        self.assertEqual(next(r for r in self.rows() if r['id'] == sid)['tier'], 'confirmed')

    def test_incremental_partial_tail_and_no_rescan(self):
        path = self.file('a.jsonl', [meta(), message(EXPRESSION)])
        self.assertEqual(self.refresh()['files_processed_this_run'], 1)
        self.assertEqual(self.refresh()['files_processed_this_run'], 0)
        raw = json.dumps(message(OTHER), ensure_ascii=False).encode()
        with path.open('ab') as f:
            f.write(raw[:80])
        self.refresh()
        self.assertEqual(len(self.rows()), 1)
        with path.open('ab') as f:
            f.write(raw[80:] + b'\n')
        self.refresh()
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.rows()[0]['sources'][0]['line'] in (2, 3), True)

    def test_compressed_archive(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('Python < 3.14')
        path = self.home / 'archived_sessions' / 'a.jsonl.zst'
        with zstd.open(path, 'wt') as f:
            f.write(json.dumps(meta()) + '\n' + json.dumps(message(EXPRESSION)) + '\n')
        self.refresh()
        self.assertEqual(self.rows()[0]['text'], EXPRESSION)

    def test_select_query_stdin_exclusion_and_json_stdout(self):
        self.file('a.jsonl', [meta('a'), message(EXPRESSION)])
        self.file('b.jsonl', [meta('b'), message(OTHER)])
        result = subprocess.run([sys.executable, str(SCRIPT), 'select', '--output-dir', str(self.output / 'cli'), '--codex-home', str(self.home), '--query-stdin', '--exclude-session-id', 'a', '--limit', '9', '--genre', '观点'], input='学习的反馈', text=True, capture_output=True, check=True)
        parsed = json.loads(result.stdout)
        self.assertEqual(len(parsed['samples']), 1)
        self.assertEqual(parsed['samples'][0]['source']['session_id'], 'b')
        self.assertEqual(parsed['query'], '学习的反馈')


    def test_default_pool_and_explicit_limit_can_exceed_three(self):
        for i in range(7):
            self.file(f'pool{i}.jsonl', [meta(f'pool{i}'), message(EXPRESSION + f'补充观察编号{i}，这个细节也影响我的判断。')])
        base = [sys.executable, str(SCRIPT), 'select', '--output-dir', str(self.output / 'cli'), '--codex-home', str(self.home)]
        parsed = json.loads(subprocess.run(base, text=True, capture_output=True, check=True).stdout)
        self.assertEqual(len(parsed['samples']), 7)
        self.assertFalse(parsed['selection_applied'])
        self.assertEqual(parsed['selection_mode'], 'candidate_pool')
        limited = json.loads(subprocess.run(base + ['--limit', '5'], text=True, capture_output=True, check=True).stdout)
        self.assertEqual(len(limited['samples']), 5)


if __name__ == '__main__':
    unittest.main()
