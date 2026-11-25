import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from unittest.mock import patch
import time
import json
from app import analytics
from app.overlay import Overlay


class UiAnalyticsTests(unittest.TestCase):
    def test_three_candidates_cache_and_repeated_fill(self):
        with tempfile.TemporaryDirectory() as root:
            client = analytics.Analytics(root, lambda *_: None)
            client.configure(True, 'phc_test', 'EU')
            with patch.object(analytics, '_client', client):
                ov = Overlay(on_fill=lambda text: None)
                ov.set_chat('synthetic')
                result = dict(candidates=['one', 'two', 'three'], best_index=1,
                              scores=[.2, .7, .1], answers={},
                              _analytics_id='test-round', _analytics_started=time.monotonic())
                ov.show(result)
                ov.app.processEvents()
                ov._check_analytics_exposure()
                ov._fill(1)
                ov._fill(1)
                ov.show_cached(result)
                ov.app.processEvents()
                ov._check_analytics_exposure()
                events = [json.loads(r[0]) for r in client.db.execute('SELECT payload FROM events')]
                self.assertEqual(sum(e['event']=='suggestion_exposed' for e in events), 1)
                clicks = [e for e in events if e['event']=='fill_clicked']
                self.assertEqual(len(clicks), 2)
                self.assertEqual(clicks[0]['properties']['position'], 1)
                self.assertEqual(clicks[0]['properties']['candidate_index'], 1)
                self.assertNotEqual(clicks[0]['properties']['attempt_id'], clicks[1]['properties']['attempt_id'])
                outcomes = [e for e in events if e['event']=='fill_execution_finished']
                self.assertTrue(all(e['properties']['status']=='executed_unverified' for e in outcomes))
                ov.win.close()
                ov.app.processEvents()
            client.db.close()


if __name__ == '__main__':
    unittest.main()
