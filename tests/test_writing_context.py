import importlib.util
from pathlib import Path
import unittest

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

if __name__=='__main__':unittest.main()
