import json
import tempfile
import unittest
from app.analytics import Analytics


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []
        self.a = Analytics(self.tmp.name, lambda host, body: self.sent.append((host, body)))

    def tearDown(self):
        self.a.db.close()
        self.tmp.cleanup()

    def enable(self):
        self.a.configure(True, 'phc_test_only', 'EU')

    def test_opt_in_and_whitelist(self):
        self.a.track('fill_clicked', suggestion_id='batch')
        self.assertEqual(self.a.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
        self.enable()
        self.a.track('fill_clicked', suggestion_id='batch', chat_text='PRIVATE', api_key='SECRET')
        self.a.flush()
        body = self.sent[0][1]
        self.assertNotIn('PRIVATE', json.dumps(body))
        self.assertNotIn('SECRET', json.dumps(body))
        self.assertFalse(body['batch'][0]['properties']['$process_person_profile'])
        self.assertEqual(self.a.db.execute('SELECT sent FROM events').fetchone()[0], 1)

    def test_failure_retry_same_identity(self):
        self.enable()
        self.a.track('suggestion_exposed', suggestion_id='batch')
        def fail(host, body):
            self.sent.append((host, body))
            raise OSError('offline')
        self.a.transport = fail
        self.a.flush()
        self.assertEqual(self.a.db.execute('SELECT sent FROM events').fetchone()[0], 0)
        self.a.transport = lambda h, b: self.sent.append((h, b))
        self.a.flush()
        self.assertEqual(self.sent[0][1], self.sent[1][1])

    def test_disable_discards_queue(self):
        self.enable()
        self.a.track('fill_clicked', suggestion_id='batch')
        self.a.configure(False, 'phc_test_only', 'EU')
        self.a.flush()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.a.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_restart_persists_identity_and_queue(self):
        self.enable()
        self.a.track('reply_copied', suggestion_id='batch')
        identity = self.a.config['installation_id']
        self.a.db.close()
        self.a = Analytics(self.tmp.name, lambda h, b: self.sent.append((h, b)))
        self.assertEqual(self.a.config['installation_id'], identity)
        self.a.flush()
        self.assertEqual(len(self.sent[0][1]['batch']), 1)

    def test_rejects_private_keys_and_other_hosts(self):
        with self.assertRaises(ValueError):
            self.a.configure(True, 'phx_private', 'EU')
        with self.assertRaises(ValueError):
            self.a.configure(True, 'phc_test', 'https://example.com')


if __name__ == '__main__':
    unittest.main()
