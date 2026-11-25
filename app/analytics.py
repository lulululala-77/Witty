"""Opt-in, content-free telemetry with a durable PostHog outbox."""
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from app.version import VERSION
from app.analytics_config import PROJECT_TOKEN, REGION

FIELDS = {'suggestion_id', 'attempt_id', 'status', 'reason', 'duration_ms',
          'candidate_count', 'candidate_index', 'position', 'recommended', 'is_test'}
EVENTS = {'app_started', 'app_exited', 'generation_started', 'generation_finished',
          'result_discarded', 'suggestion_exposed', 'fill_clicked',
          'fill_execution_finished', 'reply_copied', 'suggestion_left'}
HOSTS = {'US': 'https://us.i.posthog.com', 'EU': 'https://eu.i.posthog.com'}


class Analytics:
    def __init__(self, root=None, transport=None):
        self.root = Path(root or Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'JevChat' / 'analytics')
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.upload_lock = threading.Lock()
        self.stop = threading.Event()
        self.session = str(uuid.uuid4())
        self.transport = transport or self._send
        self.last_status = '尚未上传'
        self.db = sqlite3.connect(self.root / 'events.sqlite3', check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT, sent INTEGER DEFAULT 0)')
        row = self.db.execute('SELECT value FROM settings WHERE id=1').fetchone()
        self.config = json.loads(row[0]) if row else dict(enabled=False, token=PROJECT_TOKEN, region=REGION, installation_id=str(uuid.uuid4()))
        # Upgrade an unconfigured installation without enabling consent.
        if not self.config.get('token') and PROJECT_TOKEN:
            self.config.update(token=PROJECT_TOKEN, region=REGION)
        self.epoch = 0
        self._save()

    def _save(self):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES (1,?)', (json.dumps(self.config),))
        self.db.commit()

    def configure(self, enabled, token, region):
        if region not in HOSTS or (token and not token.startswith('phc_')) or (enabled and not token):
            raise ValueError('请选择 US/EU，并填写 phc_ 开头的项目采集 Token；不要填写个人密钥。')
        with self.lock:
            changed = token != self.config['token'] or region != self.config['region']
            self.epoch += 1
            if not enabled or changed:
                self.db.execute('DELETE FROM events WHERE sent=0')
            self.config.update(enabled=bool(enabled), token=token.strip(), region=region)
            self._save()

    def track(self, event, **props):
        if event not in EVENTS:
            return
        try:
            with self.lock:
                if not self.config['enabled']:
                    return
                clean = {k: v for k, v in props.items() if k in FIELDS and isinstance(v, (str, int, float, bool))}
                eid = str(uuid.uuid4())
                clean.update(event_id=eid, session_id=self.session, app_version=VERSION,
                             schema_version=1, ui_version='three-candidates-v1',
                             **{'$insert_id': eid, '$process_person_profile': False, '$geoip_disable': True})
                payload = dict(uuid=eid, event=event, distinct_id=self.config['installation_id'],
                               timestamp=datetime.now(timezone.utc).isoformat(), properties=clean)
                self.db.execute('INSERT INTO events(id,payload) VALUES (?,?)', (eid, json.dumps(payload)))
                # Bounded local history/outbox, including offline installations.
                self.db.execute('DELETE FROM events WHERE rowid NOT IN (SELECT rowid FROM events ORDER BY rowid DESC LIMIT 50000)')
                self.db.commit()
        except (sqlite3.Error, OSError, ValueError):
            self.last_status = '本地记录失败（不影响回复功能）'

    @staticmethod
    def _send(host, payload):
        req = Request(host + '/batch/', json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise OSError('ingestion rejected')
            body = json.loads(response.read())
            if body.get('status') not in (1, 'Ok'):
                raise OSError('ingestion not acknowledged')

    def flush(self):
        if not self.upload_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                if not self.config['enabled']:
                    return
                rows = self.db.execute('SELECT id,payload FROM events WHERE sent=0 ORDER BY rowid LIMIT 100').fetchall()
                cfg, epoch = dict(self.config), self.epoch
            if not rows:
                return
            with self.lock:
                if epoch != self.epoch or not self.config['enabled']:
                    return
            self.transport(HOSTS[cfg['region']], dict(api_key=cfg['token'], batch=[json.loads(r[1]) for r in rows]))
            with self.lock:
                if epoch == self.epoch:
                    self.db.executemany('UPDATE events SET sent=1 WHERE id=?', [(r[0],) for r in rows])
                    self.db.commit()
                    self.last_status = '最近上传成功：' + datetime.now().strftime('%H:%M:%S')
        except Exception:
            self.last_status = '上传失败，将自动重试（未输出请求内容）'
        finally:
            self.upload_lock.release()

    def start(self):
        def run():
            while not self.stop.wait(30):
                self.flush()
        threading.Thread(target=run, daemon=True, name='analytics-upload').start()
        self.track('app_started')

    def shutdown(self):
        self.track('app_exited')
        self.stop.set()  # Persist remaining events; do not block application exit.

    def status(self):
        with self.lock:
            count = self.db.execute('SELECT count(*) FROM events WHERE sent=0').fetchone()[0]
            return f'{self.last_status}；待上传 {count} 条'


_client = None


def initialize():
    global _client
    try:
        _client = Analytics()
        _client.start()
    except (OSError, sqlite3.Error, ValueError):
        _client = None


def track(event, **props):
    if _client:
        _client.track(event, **props)


def shutdown():
    if _client:
        _client.shutdown()


def open_settings(parent):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton, QMessageBox
    if not _client:
        QMessageBox.information(parent, '使用统计', '演示模式或本地数据库不可用，统计未启动。')
        return
    dialog = QDialog(parent)
    dialog.setWindowTitle('内测使用统计 · PostHog')
    layout = QVBoxLayout(dialog)
    hint = QLabel('开启后自动向所选 PostHog 美国/欧盟区域上传操作、耗时、版本和随机安装标识，\n用于改进功能及统计留存。不上传聊天内容、联系人、截图或模型密钥。\n本地最多保留 50000 条事件。关闭后清除待上传队列；已发出的请求无法撤回。\n服务端保留时间和数据删除联系渠道由内测组织者在发布说明中告知。')
    hint.setWordWrap(True)
    layout.addWidget(hint)
    enabled = QCheckBox('我同意开启使用统计（默认关闭）')
    enabled.setChecked(_client.config['enabled'])
    layout.addWidget(enabled)
    token = QLineEdit(_client.config['token'])
    token.setPlaceholderText('项目采集 Token：phc_…（不是个人密钥）')
    layout.addWidget(token)
    region = QComboBox()
    region.addItems(['EU', 'US'])
    region.setCurrentText(_client.config['region'])
    layout.addWidget(region)
    layout.addWidget(QLabel(_client.status()))
    save = QPushButton('保存统计设置')
    def apply():
        try:
            _client.configure(enabled.isChecked(), token.text().strip(), region.currentText())
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(dialog, '未保存', str(exc))
            return
        dialog.accept()
    save.clicked.connect(apply)
    layout.addWidget(save)
    dialog.exec()
