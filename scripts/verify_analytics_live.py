"""Explicit opt-in live smoke test; sends synthetic events only, never real logs."""
import argparse
import tempfile
import uuid
from app.analytics import Analytics
from app.analytics_config import PROJECT_TOKEN, REGION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true', help='Send synthetic events to configured PostHog project')
    args = parser.parse_args()
    if not args.send:
        parser.error('Use --send to explicitly authorize a live synthetic test')
    with tempfile.TemporaryDirectory() as root:
        def transport(host, payload):
            try:
                Analytics._send(host, payload)
            except Exception as exc:
                print('transport_error_type:', type(exc).__name__)
                print('http_status:', getattr(exc, 'code', None))
                print('reason:', str(getattr(exc, 'reason', ''))[:200])
                raise
        client = Analytics(root, transport)
        client.configure(True, PROJECT_TOKEN, REGION)
        sid, attempt = str(uuid.uuid4()), str(uuid.uuid4())
        common = dict(suggestion_id=sid, is_test=True)
        client.track('generation_started', **common)
        client.track('generation_finished', status='success', candidate_count=3, duration_ms=1200, **common)
        client.track('suggestion_exposed', candidate_count=3, duration_ms=1400, **common)
        client.track('fill_clicked', attempt_id=attempt, candidate_index=1, position=1, recommended=True, **common)
        client.track('fill_execution_finished', attempt_id=attempt, status='executed_unverified', duration_ms=150, **common)
        client.track('reply_copied', candidate_index=0, position=2, recommended=False, **common)
        client.track('suggestion_left', reason='app_exit', **common)
        client.flush()
        pending = client.db.execute('SELECT count(*) FROM events WHERE sent=0').fetchone()[0]
        print('region:', REGION, 'synthetic_events:', 7, 'pending:', pending)
        print('test_suggestion_id:', sid)
        print(client.last_status)
        client.db.close()
        if pending:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
