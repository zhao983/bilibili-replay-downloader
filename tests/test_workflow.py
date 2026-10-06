import contextlib
import http.server
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from bilibili_replay_downloader import downloader as app

LINK = ('https://live.bilibili.com/web-cut/quick-publish.html?'
        'start_time=1000000000&end_time=1000010358&live_key=123456789012345678')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def test_duplicate_or_non_numeric_parameters_are_rejected(self):
        for link in [LINK + '&live_key=1', LINK.replace('1000010358', '1000000000'),
                     LINK.replace('123456789012345678', '../other'), LINK + '&anchor_id=0']:
            with self.subTest(link=link), self.assertRaises(app.ReplayError):
                app.parse_link(link)

    def test_authorized_link_selects_permission_checked_api(self):
        entry = {'stream': 'https://example.com/source.m3u8'}
        with patch.object(app, 'get_json', return_value={'list': [entry]}) as get_json, \
                patch.object(app, 'read_playlist', return_value=(entry['stream'], 10358, ['playlist'])):
            result = app.save_replay(object(), LINK + '&anchor_id=77', '.', inspect_only=True)
        self.assertEqual(result['source_duration_seconds'], 10358)
        self.assertEqual(get_json.call_args.args[1], app.AUTHORIZED_API)
        self.assertEqual(get_json.call_args.args[2]['live_uid'], '77')
        self.assertEqual(get_json.call_args.args[2]['end_time'], '1000010358')

    def test_owner_link_selects_owner_api_without_two_hour_cap(self):
        entry = {'stream': 'https://example.com/source.m3u8'}
        with patch.object(app, 'get_json', return_value={'list': [entry]}) as get_json, \
                patch.object(app, 'read_playlist', return_value=(entry['stream'], 10358, ['playlist'])):
            app.save_replay(object(), LINK, '.', inspect_only=True)
        self.assertEqual(get_json.call_args.args[1], app.API)
        params = get_json.call_args.args[2]
        self.assertEqual(int(params['end_time']) - int(params['start_time']), 10358)

    def test_obviously_truncated_source_never_starts_ffmpeg(self):
        entry = {'stream': 'https://example.com/source.m3u8'}
        with patch.object(app, 'get_json', return_value={'list': [entry]}), \
                patch.object(app, 'read_playlist', return_value=(entry['stream'], 7200, ['playlist'])), \
                patch.object(app, 'run_ffmpeg') as ffmpeg:
            with self.assertRaises(app.ReplayError):
                app.save_replay(object(), LINK, '.')
            ffmpeg.assert_not_called()

    def test_login_scan_confirmation_and_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            session = SimpleNamespace(cookies=[SimpleNamespace(name='SESSDATA')])
            states = [
                {'url': 'https://account.bilibili.com/h5/account-h5/auth/scan-web?test=1', 'qrcode_key': 'test-key'},
                {'code': 86101}, {'code': 86090}, {'code': 0},
            ]
            qr = Path(directory) / 'login.png'
            with patch.object(app, 'get_json', side_effect=states), patch.object(app.time, 'sleep'):
                app.login(session, qr, open_image=False)
            self.assertTrue(qr.is_file())
            self.assertIn('登录成功', self.output.getvalue())

    def test_expired_qr_and_missing_session_are_reported(self):
        for code in (86038, 0):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                session = SimpleNamespace(cookies=[])
                states = [{'url': 'https://passport.bilibili.com/scan', 'qrcode_key': 'test-key'}, {'code': code}]
                with patch.object(app, 'get_json', side_effect=states), self.assertRaises(app.ReplayError):
                    app.login(session, Path(directory) / 'login.png', open_image=False)

    def test_foreign_qr_is_not_displayed(self):
        with tempfile.TemporaryDirectory() as directory:
            qr = Path(directory) / 'login.png'
            with patch.object(app, 'get_json', return_value={'url': 'https://example.com/login', 'qrcode_key': 'test'}), \
                    self.assertRaises(app.ReplayError):
                app.login(object(), qr, open_image=False)
            self.assertFalse(qr.exists())

    def test_permission_failure_is_actionable(self):
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                   json=lambda: {'code': 301, 'message': 'denied'})
        with self.assertRaisesRegex(app.ReplayError, '权限'):
            app.get_json(SimpleNamespace(get=lambda *a, **k: response), app.AUTHORIZED_API)

    def test_non_json_response_is_actionable(self):
        def invalid_json():
            raise ValueError('invalid')
        response = SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=invalid_json)
        with self.assertRaisesRegex(app.ReplayError, 'JSON'):
            app.get_json(SimpleNamespace(get=lambda *a, **k: response), app.API)

    def test_invalid_link_fails_before_login(self):
        with patch.object(app, 'login') as login:
            self.assertEqual(app.main(['--link', 'https://example.com/']), 1)
            login.assert_not_called()

    def test_multiple_replays_reuse_one_login_and_remove_qr(self):
        second = LINK.replace('123456789012345678', '123456789012345679')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app.Path, 'cwd', return_value=Path(directory)), \
                patch.object(app, 'save_replay') as save_replay:
            def fake_login(session, path, open_image):
                path.write_bytes(b'test qr')
            with patch.object(app, 'login', side_effect=fake_login) as login:
                code = app.main(['--link', LINK, '--link', second, '--no-open-qr'])
            self.assertEqual(code, 0)
            login.assert_called_once()
            self.assertEqual(save_replay.call_count, 2)
            self.assertFalse(list((Path(directory) / '.runtime').rglob('*.png')))

    def test_failure_keeps_partial_file_and_never_marks_it_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = {'stream': 'https://example.com/source.m3u8'}
            def fail_save(arguments, *args):
                Path(arguments[-1]).write_bytes(b'incomplete')
                raise app.ReplayError('network failed')
            with patch.object(app, 'get_json', return_value={'list': [entry]}), \
                    patch.object(app, 'read_playlist', return_value=(entry['stream'], 10358, ['playlist'])), \
                    patch.object(app, 'run_ffmpeg', side_effect=fail_save), self.assertRaises(app.ReplayError):
                app.save_replay(object(), LINK, directory)
            destination = Path(directory) / 'full_123456789012345678'
            self.assertTrue(list(destination.glob('*.partial.mp4')))
            self.assertFalse((destination / 'replay.mp4').exists())

    def test_saved_file_duration_mismatch_keeps_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = {'stream': 'https://example.com/source.m3u8'}
            def fake_save(arguments, *args):
                if arguments[-1] != '-':
                    Path(arguments[-1]).write_bytes(b'incomplete')
                return 10000
            with patch.object(app, 'get_json', return_value={'list': [entry]}), \
                    patch.object(app, 'read_playlist', return_value=(entry['stream'], 10358, ['playlist'])), \
                    patch.object(app, 'run_ffmpeg', side_effect=fake_save), self.assertRaises(app.ReplayError):
                app.save_replay(object(), LINK, directory)
            destination = Path(directory) / 'full_123456789012345678'
            self.assertFalse((destination / 'replay.mp4').exists())
            self.assertTrue(list(destination.glob('*.partial.mp4')))

    def test_logs_redact_signed_media_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'download.log'
            def fake_process(command, env, flags, error_log, expected_duration):
                error_log.write_text("failed: 'https://example.com/video?signature=private'", encoding='utf-8')
                return 3
            with patch.object(app, '_run_process', side_effect=fake_process):
                app.run_ffmpeg([], log)
            self.assertNotIn('signature', log.read_text())
            self.assertIn('[redacted URL]', log.read_text())

    def test_proxy_configuration_reaches_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, '_run_process', return_value=1) as process:
            app.run_ffmpeg([], Path(directory) / 'log', proxy='http://127.0.0.1:7890')
            self.assertEqual(process.call_args.args[1]['http_proxy'], 'http://127.0.0.1:7890')
            self.assertNotIn('NO_PROXY', process.call_args.args[1])

    def test_full_save_uses_real_http_source_and_writes_evidence(self):
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.m3u8'
            app.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=24:duration=3',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                            '-c:v', 'libx264', '-c:a', 'aac', '-f', 'hls', '-hls_list_size', '0',
                            str(source)], root / 'generate.log')
            def handler(*args, **kwargs):
                return QuietHandler(*args, directory=str(root), **kwargs)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                address = f'http://127.0.0.1:{server.server_port}/source.m3u8'
                short_link = LINK.replace('1000010358', '1000000003')
                with requests.Session() as session, patch.object(app, 'get_json', return_value={'list': [{'stream': address}]}):
                    session.trust_env = False
                    output = app.save_replay(session, short_link, root / 'output')
                metadata = json.loads((output.parent / 'metadata.json').read_text(encoding='utf-8'))
                self.assertTrue(output.is_file())
                self.assertEqual(metadata['sha256'], app.sha256_file(output))
                self.assertAlmostEqual(metadata['verified_duration_seconds'], 3, delta=0.2)
                self.assertTrue((output.parent / 'source-1.m3u8').exists())
                self.assertFalse(list(output.parent.glob('*.partial.mp4')))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_source_archive_excludes_login_and_download_files(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'package_source.py'
        spec = importlib.util.spec_from_file_location('package_source', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in module.TOP_FILES:
                (root / name).write_text('source')
            (root / 'src').mkdir()
            (root / 'src' / 'app.py').write_text('source')
            for folder, name in [('.runtime', 'login.png'), ('downloads', 'replay.mp4'), ('.venv', 'cookie.txt')]:
                destination = root / folder
                destination.mkdir()
                (destination / name).write_text('private')
            files = [str(path.relative_to(root)) for path in module.source_files(root)]
            self.assertFalse(any(name.startswith(('.runtime', 'downloads', '.venv')) for name in files))
            self.assertIn(str(Path('src') / 'app.py'), files)
