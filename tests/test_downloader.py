import tempfile
import unittest
from pathlib import Path

from bilibili_replay_downloader.downloader import ReplayError, parse_link, read_playlist, run_ffmpeg, select_stream


class Response:
    def __init__(self, url, text):
        self.url, self.text = url, text

    def raise_for_status(self):
        pass


class PlaylistSession:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return Response(url, self.responses[url])


class ReplayTests(unittest.TestCase):
    def test_long_replay_keeps_full_time_range(self):
        data = parse_link('https://live.bilibili.com/web-cut/quick-publish.html?'
                          'start_time=1000000000&end_time=1000010358&live_key=123456789012345678')
        self.assertEqual(int(data['end_time']) - int(data['start_time']), 10358)
        with self.assertRaises(ReplayError):
            parse_link('https://example.com/?live_key=1&start_time=1&end_time=3')

    def test_independent_streams_are_never_joined(self):
        with self.assertRaises(ReplayError):
            select_stream({'list': [{'stream': 'https://example.com/1'},
                                    {'stream': 'https://example.com/2'}]})

    def test_selects_complete_high_quality_source(self):
        session = PlaylistSession({
            'https://example.com/master.m3u8': '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=200\nhigh.m3u8\n',
            'https://example.com/high.m3u8': '#EXTM3U\n#EXTINF:5400,\na.ts\n#EXTINF:4958,\nb.ts\n#EXT-X-ENDLIST\n',
        })
        url, seconds, snapshots = read_playlist(session, 'https://example.com/master.m3u8')
        self.assertEqual(url, 'https://example.com/high.m3u8')
        self.assertEqual(seconds, 10358)
        self.assertEqual(len(snapshots), 2)

    def test_unfinished_source_is_rejected(self):
        session = PlaylistSession({'https://example.com/a.m3u8': '#EXTM3U\n#EXTINF:60,\na.ts\n'})
        with self.assertRaises(ReplayError):
            read_playlist(session, 'https://example.com/a.m3u8')

    def test_actual_stream_copy_preserves_every_video_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / 'source.m3u8'
            output = folder / 'saved.mp4'
            run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=24:duration=3',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
                        '-c:v', 'libx264', '-c:a', 'aac', '-f', 'hls', '-hls_time', '1',
                        '-hls_list_size', '0', str(source)], folder / 'generate.log')
            run_ffmpeg(['-i', str(source), '-map', '0:v:0', '-map', '0:a:0?',
                        '-c', 'copy', '-movflags', '+faststart', str(output)], folder / 'save.log')
            seconds = run_ffmpeg(['-i', str(output), '-map', '0:v:0', '-map', '0:a:0?',
                                 '-c', 'copy', '-f', 'null', '-'], folder / 'verify.log')
            self.assertAlmostEqual(seconds, 3, delta=0.2)
            for path, name in [(source, 'source'), (output, 'saved')]:
                run_ffmpeg(['-i', str(path), '-map', '0:v:0', '-f', 'framemd5',
                            str(folder / (name + '.md5'))], folder / (name + '.log'))
            def hashes(name):
                return [line.split(',')[-1].strip()
                        for line in (folder / (name + '.md5')).read_text().splitlines()
                        if line and not line.startswith('#')]
            original, saved = hashes('source'), hashes('saved')
            self.assertEqual(len(original), 72)
            self.assertEqual(original, saved)


if __name__ == '__main__':
    unittest.main()
