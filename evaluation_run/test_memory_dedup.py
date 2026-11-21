import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import rag, memory_dedup


class DedupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patches = [patch.object(rag, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3'),
                        patch.object(rag, '_encode', side_effect=lambda texts: np.array([[1., 0.]] * len(texts), dtype=np.float32))]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def add(self, text, **kw):
        return rag.add_memory(text, 'other_person', **{'contact': '甲', **kw})

    def test_verified_duplicate(self):
        self.add('甲不吃香菜')
        with patch.object(memory_dedup, 'is_duplicate', return_value=True) as verify:
            self.assertEqual(self.add('甲一直不吃香菜'), 0)
            self.assertEqual(verify.call_args.args[1][0]['content'], '甲不吃香菜')

    def test_high_similarity_change_preserved(self):
        self.add('甲住上海')
        with patch.object(memory_dedup, 'is_duplicate', return_value=False):
            self.assertGreater(self.add('甲已搬到苏州'), 0)

    def test_candidate_threshold(self):
        self.add('甲不吃香菜')
        for score, expected in [(0.84, 1), (0.79, 0)]:
            vector = np.array([[score, (1-score**2)**0.5]], dtype=np.float32)
            with self.subTest(score=score), patch.object(rag, '_encode', return_value=vector), \
                    patch.object(memory_dedup, 'is_duplicate', return_value=True) as verify:
                self.add('同义改写')
                self.assertEqual(len(verify.call_args.args[1]), expected)

    def test_exact_duplicate_needs_no_model(self):
        self.add('甲不吃香菜')
        with patch.object(memory_dedup, 'is_duplicate') as verify:
            self.assertEqual(self.add('甲不吃香菜'), 0)
            verify.assert_not_called()

    def test_other_contact_not_a_candidate(self):
        self.add('不吃香菜', contact='乙')
        with patch.object(memory_dedup, 'is_duplicate', return_value=False) as verify:
            self.assertGreater(self.add('不吃香菜'), 0)
            self.assertEqual(verify.call_args.args[1], [])

    def test_expired_memory_not_a_candidate(self):
        self.add('今天不接电话', expires_at='2000-01-01 00:00:00')
        with patch.object(memory_dedup, 'is_duplicate', return_value=False) as verify:
            self.assertGreater(self.add('今天不接电话'), 0)
            self.assertEqual(verify.call_args.args[1], [])

    def test_changed_date_not_a_candidate(self):
        self.add('约定吃饭', event_date='2026-11-21')
        with patch.object(memory_dedup, 'is_duplicate', return_value=False) as verify:
            self.assertGreater(self.add('约定吃饭', event_date='2026-11-22'), 0)
            self.assertEqual(verify.call_args.args[1], [])

    def test_missing_vector_preserves_new_memory(self):
        self.add('甲不吃香菜')
        with patch.object(rag, '_encode', side_effect=RuntimeError('offline')):
            self.assertGreater(self.add('甲不吃香菜，并且花生过敏'), 0)

    def test_verifier_rejects_malformed_or_unavailable_output(self):
        candidates = [{'id': 1, 'content': '甲不吃香菜'}]
        with patch('app.settings.llm_key', return_value='test'), patch('core.jev_client._api_key', return_value='test'):
            for raw in ['{"duplicate_of":1,"duplicate_of":null}', '{"duplicate_of":true}',
                        '{"duplicate_of":2}', '{"duplicate_of":1,"extra":1}', 'not JSON']:
                with self.subTest(raw=raw), patch('core.llm.chat', return_value=raw):
                    self.assertFalse(memory_dedup.is_duplicate({}, candidates))
            with patch('core.llm.chat', side_effect=RuntimeError('offline')):
                self.assertFalse(memory_dedup.is_duplicate({}, candidates))
            with patch('core.llm.chat', return_value='{"duplicate_of":1}'):
                self.assertTrue(memory_dedup.is_duplicate({}, candidates))


if __name__ == '__main__':
    unittest.main()
