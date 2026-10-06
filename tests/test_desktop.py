import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bilibili_replay_downloader import downloader as core
from bilibili_replay_downloader.desktop import DesktopController

LINK = ('https://live.bilibili.com/web-cut/quick-publish.html?'
        'start_time=1000000000&end_time=1000010358&live_key=123456789012345678')


class DesktopTests(unittest.TestCase):
    def wait(self, controller):
        controller.worker.join(timeout=5)
        self.assertFalse(controller.busy)

    def test_successful_login_is_reused_for_two_downloads_and_closed(self):
        events = []
        controller = DesktopController(lambda kind, data: events.append((kind, data)))
        with tempfile.TemporaryDirectory() as temporary, patch.object(core, 'login') as login, \
                patch.object(core, 'save_replay', return_value=Path(temporary) / 'replay.mp4') as save:
            controller.start('login')
            self.wait(controller)
            session = controller.session
            self.assertIsNotNone(session)
            self.assertFalse(session.trust_env)
            for _ in range(2):
                controller.start('download', LINK, temporary)
                self.wait(controller)
            login.assert_called_once()
            self.assertEqual(save.call_count, 2)
            self.assertIs(save.call_args.args[0], session)
            self.assertEqual(sum(kind == 'complete' for kind, _ in events), 2)
            controller.close()
            self.assertIsNone(controller.session)

    def test_invalid_link_never_starts_login_or_creates_directory(self):
        controller = DesktopController(lambda *args: None)
        with tempfile.TemporaryDirectory() as temporary, patch.object(core, 'login') as login:
            folder = Path(temporary) / 'new'
            with self.assertRaises(core.ReplayError):
                controller.start('download', 'https://example.com/', folder)
            self.assertFalse(folder.exists())
            self.assertIsNone(controller.worker)
            login.assert_not_called()

    def test_cancelled_login_leaves_no_session_or_qr_file(self):
        events, paths = [], []
        controller = DesktopController(lambda kind, data: events.append((kind, data)))
        entered = threading.Event()
        def login(session, path, open_image, control):
            path.write_bytes(b'offline qr')
            paths.append(path)
            entered.set()
            control.cancelled.wait(3)
            control.check()
        with patch.object(core, 'login', side_effect=login):
            controller.start('login')
            self.assertTrue(entered.wait(3))
            controller.cancel()
            self.wait(controller)
        self.assertIsNone(controller.session)
        self.assertFalse(paths[0].exists())
        self.assertIn('cancelled', [kind for kind, _ in events])

    def test_cancel_stops_ffmpeg_even_when_it_has_no_progress_output(self):
        # A real-time source would otherwise take sixty seconds to finish.
        events = []
        control = core.TaskControl(lambda kind, data: events.append(kind))
        timer = threading.Timer(0.6, control.cancelled.set)
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as temporary:
            timer.start()
            try:
                with self.assertRaises(core.CancelledError):
                    core.run_ffmpeg(['-re', '-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=24:duration=60',
                                     '-f', 'null', '-'], Path(temporary) / 'cancel.log', control=control)
            finally:
                timer.cancel()
        self.assertLess(time.monotonic() - started, 6)

    def test_qr_is_sent_to_gui_as_bytes_and_no_external_image_is_opened(self):
        events = []
        control = core.TaskControl(lambda kind, data: events.append((kind, data)))
        session = type('Session', (), {'cookies': [type('Cookie', (), {'name': 'SESSDATA'})()]})()
        states = [{'url': 'https://account.bilibili.com/scan', 'qrcode_key': 'offline-test'}, {'code': 0}]
        with tempfile.TemporaryDirectory() as temporary, patch.object(core, 'get_json', side_effect=states):
            core.login(session, Path(temporary) / 'login.png', False, control=control)
        qr = next(data['image'] for kind, data in events if kind == 'qr')
        self.assertTrue(qr.startswith(b'\x89PNG'))
        self.assertIn('logged_in', [kind for kind, _ in events])

    def test_windowless_operation_does_not_require_stdout(self):
        control = core.TaskControl(lambda *args: None)
        with patch.object(core.sys, 'stdout', None):
            core.report('ready', control)
            core.report('ready')


if __name__ == '__main__':
    unittest.main()
