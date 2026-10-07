import io
import json
import tempfile
import unittest
import importlib.util
import os
import threading
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

from app import App, Problem, Service, TOOLS, factory, iso, now, openapi


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = Service(Path(self.tmp.name) / 'test.sqlite3')
        self.alice = self.service.issue_token('alice')
        self.bob = self.service.issue_token('bob')
        self.future = iso(now() + timedelta(days=3))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, args, token=None, key='test-key-123'):
        return self.service.call(token or self.alice, name, args, key)['result']

    def notice(self, **extra):
        return dict(title='测试就业培训（模拟，不能用于报名）', source_url='https://example.org/training', city='广州', topic='就业', summary='模拟公告', deadline_at=self.future, **extra)

    def create(self):
        return self.call('create_followup', dict(title='核对报名', due_at=self.future, confirmed=True))

    def test_public_deployment_reseeds_and_disables_private_routes(self):
        with patch.dict(os.environ, {'HIDEAR_DATABASE': str(Path(self.tmp.name) / 'demo.sqlite3'), 'HIDEAR_PUBLIC_ONLY': '1'}):
            deployed = factory()
            deployed = factory()  # restart must not duplicate source records
        statuses = []
        def request(path, arguments, token=''):
            body = json.dumps(arguments).encode()
            environment = {'PATH_INFO': path, 'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body), 'HTTP_AUTHORIZATION': 'Bearer ' + token}
            return json.loads(b''.join(deployed(environment, lambda status, headers: statuses.append(status))))
        response = request('/public/tools/search_information', {'query': '补贴', 'city': '北京'})
        self.assertEqual(response['result']['total'], 1)
        identity = response['result']['items'][0]['id']
        self.assertEqual(request('/public/tools/prepare_action', {'information_id': identity})['result']['eligibility_status'], 'not_determined')
        token = deployed.service.issue_token('test')
        self.assertFalse(request('/tools/create_followup', {'title': 'test', 'due_at': self.future, 'confirmed': True}, token)['success'])
        self.assertTrue(statuses[-1].startswith('404'))

    def test_user_isolation(self):
        item = self.create()
        self.assertEqual(self.call('list_followups', {}, self.bob)['items'], [])
        with self.assertRaises(Problem) as caught:
            self.call('update_followup', dict(followup_id=item['id'], version=1, status='completed', confirmed=True), self.bob)
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(Problem):
            self.service.calendar(self.bob, item['id'])

    def test_idempotent_write_and_conflict(self):
        first = self.create()
        self.assertEqual(first, self.create())
        self.assertEqual(len(self.call('list_followups', {})['items']), 1)
        with self.assertRaises(Problem) as caught:
            self.call('create_followup', dict(title='不同事项', due_at=self.future, confirmed=True))
        self.assertEqual(caught.exception.code, 'idempotency_conflict')

    def test_confirmation_and_auth(self):
        with self.assertRaises(Problem):
            self.call('create_followup', dict(title='报名', due_at=self.future, confirmed=False))
        with self.assertRaises(Problem) as caught:
            self.call('list_followups', {}, 'bad-token')
        self.assertEqual(caught.exception.status, 401)

    def test_expired_token(self):
        expired = self.service.issue_token('expired', days=-1)
        with self.assertRaises(Problem):
            self.call('list_followups', {}, expired)

    def test_unknown_fields_and_strict_types(self):
        for args in ({'user_id': 'bob'}, {'limit': True}, {'limit': 0}, {'include_expired': 'false'}):
            with self.assertRaises(Problem):
                self.call('search_information', args)

    def test_expired_and_withdrawn_information(self):
        record = self.notice()
        record['deadline_at'] = iso(now() - timedelta(days=1))
        saved = self.service.import_public(record)
        self.assertEqual(self.call('search_information', {})['items'], [])
        self.assertEqual(len(self.call('search_information', {'include_expired': True})['items']), 1)
        with self.assertRaises(Problem) as caught:
            self.call('prepare_action', {'information_id': saved['id']})
        self.assertEqual(caught.exception.code, 'not_actionable')
        record['deadline_at'] = self.future
        record['verification_status'] = 'withdrawn'
        self.service.import_public(record)
        self.assertEqual(self.call('search_information', {})['items'], [])

    def test_private_intake_and_no_verification_forgery(self):
        saved = self.call('save_information', self.notice())
        self.assertEqual(saved['verification_status'], 'unverified')
        self.assertEqual(self.call('search_information', {}, self.bob)['items'], [])
        with self.assertRaises(Problem):
            self.call('get_information', {'information_id': saved['id']}, self.bob)
        with self.assertRaises(Problem):
            self.call('save_information', self.notice(verification_status='verified'))

    def test_information_deduplication_and_missing_fields(self):
        first = self.service.import_public(self.notice())
        second = self.service.import_public(self.notice())
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.call('search_information', {})['total'], 1)
        plan = self.call('prepare_action', {'information_id': first['id']})
        self.assertEqual(plan['materials'], [])
        self.assertEqual(plan['submission_status'], 'not_submitted')
        self.assertEqual(plan['eligibility_status'], 'not_determined')
        self.assertEqual(plan['verification_status'], 'unverified')

    def test_verification_requires_evidence(self):
        with self.assertRaises(Problem):
            self.service.import_public(self.notice(verification_status='verified'))
        saved = self.service.import_public(self.notice(verification_status='verified', checked_at=iso(now()), verification_evidence='模拟人工核验', materials=['材料A'], conditions=['条件A']))
        plan = self.call('prepare_action', {'information_id': saved['id']})
        self.assertEqual(plan['materials'], ['材料A'])
        self.assertIsNone(plan['action_url'])

    def test_dates_and_urls(self):
        for date in ('2027-01-01T10:00:00', 'not-a-time', iso(now() - timedelta(seconds=10))):
            with self.assertRaises(Problem):
                self.call('create_followup', dict(title='报名', due_at=date, confirmed=True))
        for source in ('javascript:alert(1)', 'http://example.org', 'https://user:pass@example.org'):
            data = self.notice()
            data['source_url'] = source
            with self.assertRaises(Problem):
                self.call('save_information', data)

    def test_version_conflict_and_cancellation(self):
        item = self.create()
        changed = self.call('update_followup', dict(followup_id=item['id'], version=1, status='cancelled', confirmed=True), key='update-key-1')
        self.assertEqual(changed['version'], 2)
        with self.assertRaises(Problem):
            self.call('update_followup', dict(followup_id=item['id'], version=1, status='completed', confirmed=True), key='update-key-2')
        self.assertEqual(self.call('list_followups', {})['items'], [])
        with self.assertRaises(Problem):
            self.service.calendar(self.alice, item['id'])

    def test_notification_and_ical(self):
        item = self.create()
        self.assertEqual(item['notification_status'], 'not_configured')
        content = self.service.calendar(self.alice, item['id'])
        self.assertIn('BEGIN:VALARM\r\n', content)
        self.assertIn('TRIGGER:PT0S', content)
        self.assertIn('Z\r\nSUMMARY:', content)
        self.assertTrue(all(len(line.encode()) <= 73 for line in content.split('\r\n')))

    def test_due_items(self):
        item = self.create()
        self.assertEqual(self.call('list_followups', {'due_only': True})['items'], [])
        with self.service.connection() as db:
            item['due_at'] = iso(now() - timedelta(minutes=1))
            db.execute('UPDATE followups SET data=? WHERE id=?', (json.dumps(item), item['id']))
        self.assertEqual(len(self.call('list_followups', {'due_only': True})['items']), 1)

    def test_http_auth_invalid_json_and_request_limits(self):
        app = App(self.service)
        def request(path, method='POST', body=b'{}', auth=None, length=None):
            env = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(body) if length is None else length), 'wsgi.input': io.BytesIO(body)}
            if auth:
                env['HTTP_AUTHORIZATION'] = 'Bearer ' + auth
            statuses = []
            data = b''.join(app(env, lambda status, headers: statuses.append(status)))
            return int(statuses[0].split()[0]), json.loads(data)
        self.assertEqual(request('/tools/list_followups')[0], 401)
        self.assertEqual(request('/tools/list_followups', auth=self.alice)[0], 200)
        self.assertEqual(request('/tools/list_followups', body=b'{bad', auth=self.alice)[0], 400)
        self.assertEqual(request('/tools/list_followups', auth=self.alice, length=20000)[0], 413)
        self.assertFalse(request('/tools/list_followups', auth=self.alice, body=b'[]')[1]['success'])
        self.assertEqual(request('/tools/unknown', auth=self.alice)[0], 404)
        self.assertTrue({'/tools/' + name for name in TOOLS} <= set(openapi()['paths']))

    def test_public_interface_never_returns_private_records(self):
        private = self.call('save_information', self.notice())
        app = App(self.service)
        def public(name, args):
            body = json.dumps(args).encode()
            env = {'PATH_INFO': '/public/tools/' + name, 'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
            codes = []
            output = b''.join(app(env, lambda status, headers: codes.append(int(status.split()[0]))))
            return codes[0], json.loads(output)
        self.assertEqual(public('search_information', {})[1]['result']['total'], 0)
        self.assertEqual(public('get_information', {'information_id': private['id']})[0], 404)
        self.assertEqual(public('list_followups', {})[0], 404)
        self.service.import_public(self.notice())
        self.assertEqual(public('search_information', {})[1]['result']['total'], 1)
        self.assertEqual(public('search_information', {})[1]['code'], 0)

    def test_skill_script_calls_real_http_service(self):
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        class Quiet(WSGIRequestHandler):
            def log_message(self, *_):
                pass
        client_path = Path(__file__).resolve().parents[1] / 'skills/hidear-information-action/scripts/hidear_tool.py'
        definition = importlib.util.spec_from_file_location('hidear_client', client_path)
        client = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(client)
        token_file = Path(self.tmp.name) / 'client.token'
        token_file.write_text(self.alice, encoding='utf-8')
        with make_server('127.0.0.1', 0, App(self.service), handler_class=Quiet) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.dict(os.environ, {'HIDEAR_BASE_URL': f'http://127.0.0.1:{server.server_port}', 'HIDEAR_TOKEN_FILE': str(token_file)}):
                    result = client.run('create_followup', {'title': 'Skill实际调用测试', 'due_at': self.future, 'confirmed': True}, 'skill-http-key')
                    self.assertTrue(result['success'])
                    listed = client.run('list_followups', {})
                    self.assertEqual(listed['result']['items'][0]['id'], result['result']['id'])
                    self.assertEqual(result['result']['notification_status'], 'not_configured')
                    duplicate = client.run('create_followup', {'title': 'Skill实际调用测试', 'due_at': self.future, 'confirmed': True}, 'skill-http-key')
                    self.assertEqual(duplicate, result)
            finally:
                server.shutdown()
                thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
