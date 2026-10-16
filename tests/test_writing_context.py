import importlib.util
from pathlib import Path
import unittest
import json
import subprocess
import sys

spec = importlib.util.spec_from_file_location('writing_context', Path(__file__).resolve().parents[1] / 'scripts/writing_context.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class WritingContextTests(unittest.TestCase):
    def test_preserves_method_and_omits_retrieval(self):
        method = '## Write and review\n\nKeep the supplied voice.\n'
        text = '# Example\n## Retrieval\nDo not cache.\n' + method + '## Other\nNot writing.\n'
        self.assertEqual(m.official_method(text), method)
        self.assertNotIn('Do not cache', m.render(text, [])['prompt'])
    def test_unknown_version_fails_loudly(self):
        for text in ('# Changed format', '## Write and review\n', '## Write and review\na\n## Write and review\nb'):
            with self.assertRaises(ValueError): m.official_method(text)
    def test_reference_attribution_and_provenance(self):
        sample={'id':'fixture', 'text':'synthetic writing', 'tier':'confirmed', 'authorship':{'status':'human_confirmed'}, 'sources':[{'path':'fixture.jsonl','session_id':'fixture','line':1}]}
        result=m.render('## Write and review\nKeep the voice.\n',[sample])
        self.assertIn('synthetic writing',result['prompt'])
        sample['authorship']['status']='inferred_not_verified'
        with self.assertRaises(ValueError):m.render('## Write and review\nKeep the voice.\n',[sample])
    def test_rejects_duplicates_and_ineligible(self):
        s={'id':'explicit','text':'example','tier':'explicit','authorship':{'status':'user_provided_not_verified'},'sources':[{'path':'current_request'}]}
        with self.assertRaises(ValueError):m.render('## Write and review\nKeep.\n',[s,s])
        s['reference_eligible']=False
        with self.assertRaises(ValueError):m.render('## Write and review\nKeep.\n',[s])

    def fixtures(self, count=7):
        return [{'id':f'original{i}', 'text':f'Unique synthetic prose {i}', 'tier':'confirmed',
                 'authorship':{'status':'human_confirmed'}, 'reference_eligible':True,
                 'sources':[{'path':'fixture.jsonl','session_id':f'session{i % 2}','line':i+1}]}
                for i in range(count)]

    def test_adaptive_selection_preserves_all_chosen_and_method(self):
        candidates = self.fixtures()
        pack = m.selection_prompt(candidates, 'new topic', 'short prose')
        data = json.loads(pack['prompt'].split('\n', 1)[1])
        self.assertEqual(len(data['candidates']), 7)
        chosen = m.resolve_selection(candidates, {'selected_ids':['R7','R2','R3','R4','R5']})['samples']
        self.assertEqual([x['id'] for x in chosen], ['original6','original1','original2','original3','original4'])
        method = '## Write and review\nKeep the voice.\n'
        rendered = m.render(method, chosen)['prompt']
        self.assertTrue(rendered.startswith(method))
        refs = json.loads(rendered.split('以下为参考数据。\n',1)[1])
        self.assertEqual(len(refs), 5)
        self.assertNotIn('Unique synthetic prose 0', rendered)

    def test_selection_accepts_zero_one_or_entire_pool(self):
        candidates = self.fixtures()
        for keys in ([], ['R1'], [f'R{i}' for i in range(1, 8)]):
            result = m.resolve_selection(candidates, json.dumps({'selected_ids':keys}))
            self.assertEqual(len(result['samples']), len(keys))
        fenced = '```json\n' + json.dumps({'selected_ids':['R1']}) + '\n```'
        self.assertEqual(len(m.resolve_selection(candidates, fenced)['samples']),1)

    def test_selection_rejects_unknown_duplicates_and_wrong_shape(self):
        for selection in ({'selected_ids':['R99']},{'selected_ids':['R1','R1']},{'selected_ids':'R1'},{'selected_ids':[1]}):
            with self.assertRaises(ValueError):m.resolve_selection(self.fixtures(),selection)

    def test_cli_selection_without_official_plugin(self):
        script=Path(__file__).resolve().parents[1]/'scripts/writing_context.py'
        data={'samples':self.fixtures(),'query':'new topic'}
        p=subprocess.run([sys.executable,str(script),'--selection-prompt'],input=json.dumps(data),capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(p.stdout)['candidate_count'],7)
        data['selection']={'selected_ids':['R1','R2','R3','R4','R5']}
        p=subprocess.run([sys.executable,str(script),'--resolve-selection'],input=json.dumps(data),capture_output=True,text=True,check=True)
        self.assertEqual(len(json.loads(p.stdout)['samples']),5)


if __name__=='__main__':unittest.main()
