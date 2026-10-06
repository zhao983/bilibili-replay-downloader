"""Offline desktop/bundle smoke check, using only a local generated replay."""
import functools
import http.server
import json
from pathlib import Path
import tempfile
import threading
import time
import traceback
import sys
import ssl

from PIL import ImageGrab
import qrcode
import requests

from . import downloader as core


def run_check(window, report_file):
    report_file = Path(report_file).resolve()
    report_file.parent.mkdir(parents=True, exist_ok=True)
    resources = []
    deadline = time.monotonic() + 60

    def finish(result):
        report_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        for close in reversed(resources):
            close()
        window.controller.close()
        window.root.destroy()

    try:
        # Certificates must come from the bundle, not a system Python install.
        ssl.create_default_context(cafile=requests.certs.where())
        window.root.update_idletasks()
        def screenshot(name):
            root = window.root
            box = (root.winfo_rootx(), root.winfo_rooty(),
                   root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
            ImageGrab.grab(bbox=box).save(report_file.parent / name)
        screenshot('desktop-preview.png')
        temp = tempfile.TemporaryDirectory(prefix='bili-replay-check-')
        resources.append(temp.cleanup)
        root = Path(temp.name)
        source = root / 'source.m3u8'
        core.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=24:duration=3',
                         '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                         '-c:v', 'libx264', '-c:a', 'aac', '-f', 'hls', '-hls_list_size', '0',
                         str(source)], root / 'generate.log')
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                  functools.partial(QuietHandler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        resources.append(server.server_close)
        resources.append(server.shutdown)
        address = f'http://127.0.0.1:{server.server_port}/source.m3u8'
        class Response:
            status_code = 200
            def __init__(self, data):
                self.data = data
            def raise_for_status(self):
                pass
            def json(self):
                return {'code': 0, 'data': self.data}
        class FixtureSession(requests.Session):
            def get(self, url, **kwargs):
                if url == core.PASSPORT + 'generate':
                    return Response({'url': 'https://account.bilibili.com/scan?offline-test=1',
                                     'qrcode_key': 'offline-test'})
                if url == core.PASSPORT + 'poll':
                    self.cookies.set('SESSDATA', 'offline-test')
                    return Response({'code': 0})
                if url == core.API:
                    return Response({'list': [{'stream': address}]})
                assert url.startswith(f'http://127.0.0.1:{server.server_port}/'), 'Unexpected network request'
                return super().get(url, **kwargs)
        window.controller.session_factory = FixtureSession
        seen_qr = []
        original_event = window.event
        def capture_event(kind, data):
            original_event(kind, data)
            if kind == 'qr':
                assert window.qr_photo is not None
                seen_qr.append(True)
        window.event = capture_event
        folder = root / '中文保存位置 with spaces'
        # Exercise the actual browse handler without displaying a modal native dialog.
        from . import desktop
        original_choose = desktop.filedialog.askdirectory
        desktop.filedialog.askdirectory = lambda **kwargs: str(folder)
        try:
            window.choose_button.invoke()
            assert window.folder.get() == str(folder)
        finally:
            desktop.filedialog.askdirectory = original_choose
        original_error = desktop.messagebox.showerror
        errors = []
        desktop.messagebox.showerror = lambda *args, **kwargs: errors.append(args)
        resources.append(lambda: setattr(desktop.messagebox, 'showerror', original_error))
        window.link.insert('1.0', 'https://example.com/invalid')
        window.download_button.invoke()
        assert errors and window.controller.worker is None
        errors.clear()
        window.link.delete('1.0', 'end')
        window.link.insert('1.0', 'https://live.bilibili.com/web-cut/quick-publish.html?'
                           'start_time=1000000000&end_time=1000000003&live_key=123456789012345678')
        window.download_button.invoke()
        assert str(window.download_button['state']) == 'disabled'
    except Exception as exc:
        finish({'ok': False, 'error': str(exc), 'traceback': traceback.format_exc()})
        return

    def check_done():
        if window.controller.busy:
            if time.monotonic() > deadline:
                window.controller.cancel()
            window.root.after(100, check_done)
            return
        # Drain queued events before asserting the visible completion state.
        while not window.events.empty():
            window.event(*window.events.get_nowait())
        try:
            assert not errors, str(errors)
            assert seen_qr, 'QR image did not render'
            assert window.output_file and window.output_file.exists()
            assert float(window.progress['value']) == 100
            metadata = json.loads((window.output_file.parent / 'metadata.json').read_text(encoding='utf-8'))
            assert metadata['sha256'] == core.sha256_file(window.output_file)
            assert abs(metadata['verified_duration_seconds'] - 3) < 0.2
            hashes = []
            for item, name in ((source, 'source'), (window.output_file, 'saved')):
                md5 = root / (name + '.md5')
                core.run_ffmpeg(['-i', str(item), '-map', '0:v:0', '-f', 'framemd5', str(md5)], root / (name + '.log'))
                hashes.append([line.split(',')[-1].strip() for line in md5.read_text().splitlines()
                               if line and not line.startswith('#')])
            assert len(hashes[0]) == 72 and hashes[0] == hashes[1]
            window.root.update_idletasks()
            screenshot('desktop-complete.png')
            assert window.controller.session is not None
            window.controller.close()
            assert window.controller.session is None
            finish({'ok': True, 'frozen': bool(getattr(sys, 'frozen', False)),
                    'frames_preserved': 72, 'duration_seconds': metadata['verified_duration_seconds'],
                    'checks': ['GUI startup', 'folder browse', 'invalid link', 'QR login events',
                               'bundled FFmpeg', 'Chinese path', 'full local HLS save',
                               'progress and completion', 'file hash', 'logout on close']})
        except Exception as exc:
            finish({'ok': False, 'error': str(exc), 'traceback': traceback.format_exc()})
    window.root.after(100, check_done)
