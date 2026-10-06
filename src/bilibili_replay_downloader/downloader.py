# -*- coding: utf-8 -*-
"""Save an owner's complete replay, without cutting or re-encoding it."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tempfile
import uuid
import webbrowser
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

import imageio_ffmpeg
import qrcode
import requests

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')
API = 'https://api.live.bilibili.com/xlive/app-blink/v1/anchorVideo/GetSliceStream'
AUTHORIZED_API = 'https://api.live.bilibili.com/xlive/web-room/v1/videoService/GetUserSliceStream'
PASSPORT = 'https://passport.bilibili.com/x/passport-login/web/qrcode/'


class ReplayError(Exception):
    pass


def parse_link(link):
    parsed = urlsplit(link.strip())
    if (parsed.scheme not in ('http', 'https') or parsed.hostname != 'live.bilibili.com'
            or parsed.path not in ('/web-cut/quick-publish.html',
                                   '/web-cut/quick-publish-mobile.html', '/web-cut/index.html')):
        raise ReplayError('请输入自己的直播回放剪辑页面链接（/web-cut/…）。')
    query = parse_qs(parsed.query)
    values = {}
    for name in ('live_key', 'start_time', 'end_time'):
        value = query.get(name, [])
        if len(value) != 1 or not re.fullmatch(r'[0-9]{1,64}', value[0]):
            raise ReplayError(f'回放链接缺少有效的 {name} 参数。')
        values[name] = value[0]
    if int(values['end_time']) <= int(values['start_time']):
        raise ReplayError('回放链接的结束时间必须晚于开始时间。')
    if 'anchor_id' in query:
        anchor = query['anchor_id']
        if len(anchor) != 1 or not re.fullmatch(r'[1-9][0-9]{0,19}', anchor[0]):
            raise ReplayError('回放链接的主播编号无效。')
        values['live_uid'] = anchor[0]
    return values


def get_json(session, url, params=None):
    response = session.get(url, params=params, timeout=30)
    if response.status_code == 412:
        raise ReplayError('B站返回 HTTP 412，请稍后重试或检查网络连接。')
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ReplayError('B站接口没有返回有效的 JSON 数据。') from exc
    if not isinstance(payload, dict) or payload.get('code') != 0:
        code = payload.get('code') if isinstance(payload, dict) else '未知'
        message = payload.get('message') if isinstance(payload, dict) else '返回数据异常'
        if code == -101:
            raise ReplayError('登录会话无效，请重新扫码登录。')
        if code == 301:
            raise ReplayError('当前账号没有该主播回放的剪辑权限。')
        raise ReplayError(f'B站接口返回 {code}：{message}')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ReplayError('B站接口未返回有效数据。')
    return data


def login(session, qr_path, open_image=True, timeout=180):
    data = get_json(session, PASSPORT + 'generate')
    qr_url = data.get('url', '')
    qr_address = urlsplit(qr_url)
    if (qr_address.scheme != 'https'
            or qr_address.hostname not in ('passport.bilibili.com', 'account.bilibili.com')
            or not data.get('qrcode_key')):
        raise ReplayError('登录接口未提供有效二维码。')
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(qr_url).save(qr_path)
    print(f'二维码已生成：{qr_path}', flush=True)
    print('请用手机B站App扫描二维码并确认登录。登录信息仅用于本次运行，不保存到文件。', flush=True)
    if open_image:
        try:
            if sys.platform.startswith('win'):
                os.startfile(str(qr_path))
            else:
                webbrowser.open(qr_path.resolve().as_uri())
        except OSError:
            print('未能自动打开图片，请手动打开上面的二维码文件。', flush=True)
    deadline = time.monotonic() + timeout
    previous_code = None
    while time.monotonic() < deadline:
        status = get_json(session, PASSPORT + 'poll', {'qrcode_key': data['qrcode_key']})
        code = status.get('code')
        if code == 0:
            # Passport normally sets the .bilibili.com session cookie itself.
            if not any(cookie.name == 'SESSDATA' for cookie in session.cookies):
                raise ReplayError('扫码成功，但未收到登录会话，请重试。')
            print('登录成功。正在获取整场回放的视频流……', flush=True)
            return
        if code == 86038:
            raise ReplayError('二维码已过期，请重新运行。')
        if code not in (86101, 86090):
            raise ReplayError(f'扫码登录状态异常：{code}')
        if code != previous_code:
            print('等待手机确认登录……' if code == 86090 else '等待扫码……', flush=True)
            previous_code = code
        time.sleep(2)
    raise ReplayError('扫码等待超时，请重新运行。')


def select_stream(data):
    entries = data.get('list')
    if not isinstance(entries, list) or not entries:
        raise ReplayError('未取得可播放的视频流，请检查回放是否仍在有效期内。')
    if len(entries) != 1:
        raise ReplayError('平台返回了多条独立视频流。为避免拼接痕迹，本工具不会自动拼接，请保留此提示进一步排查。')
    entry = entries[0]
    if not isinstance(entry, dict) or not entry.get('stream'):
        raise ReplayError('回放视频流格式异常。')
    url = entry['stream']
    parsed = urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        raise ReplayError('回放视频流地址无效。')
    return entry


def read_playlist(session, url):
    """Select the best rendition and measure the full, finished source playlist."""
    snapshots = []
    for _ in range(5):
        response = session.get(url, timeout=30)
        response.raise_for_status()
        text = response.text.lstrip('\ufeff')
        if not text.startswith('#EXTM3U'):
            raise ReplayError('接口没有返回可验证的完整播放列表。')
        snapshots.append(text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        variants = []
        for i, line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:'):
                bandwidth = re.search(r'(?:^|,)BANDWIDTH=(\d+)', line.split(':', 1)[1])
                if i + 1 < len(lines) and not lines[i + 1].startswith('#'):
                    variants.append((int(bandwidth.group(1)) if bandwidth else 0,
                                     urljoin(response.url, lines[i + 1])))
        if variants:
            url = max(variants, key=lambda variant: variant[0])[1]
            continue
        if '#EXT-X-ENDLIST' not in lines:
            raise ReplayError('视频流尚未结束，无法保证保存的是整场回放。')
        try:
            duration = sum(float(line.split(':', 1)[1].split(',', 1)[0])
                           for line in lines if line.startswith('#EXTINF:'))
        except ValueError as exc:
            raise ReplayError('播放列表的时长数据异常。') from exc
        if not math.isfinite(duration) or duration <= 0:
            raise ReplayError('完整播放列表中没有有效的视频时长。')
        return response.url, duration, snapshots
    raise ReplayError('播放列表嵌套过深，无法确认完整视频。')


def run_ffmpeg(arguments, error_log, expected_duration=None, proxy=None):
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    environment = os.environ.copy()
    for name in list(environment):
        if name.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
            environment.pop(name)
    if proxy:
        environment['http_proxy'] = proxy
        environment['https_proxy'] = proxy
    else:
        environment['NO_PROXY'] = '*'
    command = [executable, '-hide_banner', '-loglevel', 'warning', '-nostdin',
               '-nostats', '-progress', 'pipe:1'] + arguments
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith('win') else 0
    try:
        return _run_process(command, environment, flags, error_log, expected_duration)
    finally:
        if error_log.exists():
            # Logs are useful for bug reports, but signed media URLs are private.
            original = error_log.read_text(encoding='utf-8', errors='replace')
            redacted = re.sub(r'https?://[^\s\]\x27\"]+', '[redacted URL]', original)
            error_log.write_text(redacted, encoding='utf-8')


def _run_process(command, environment, flags, error_log, expected_duration):
    last_report = 0
    output_seconds = 0
    with error_log.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log,
                                   text=True, encoding='utf-8', errors='replace',
                                   env=environment, creationflags=flags)
        try:
            for line in process.stdout:
                key, _, value = line.strip().partition('=')
                if key == 'out_time_us' and value.lstrip('-').isdigit():
                    output_seconds = max(0, int(value) / 1_000_000)
                    if expected_duration and time.monotonic() - last_report >= 10:
                        percentage = min(100, output_seconds / expected_duration * 100)
                        print(f'已保存 {output_seconds / 60:.1f} 分钟 / {expected_duration / 60:.1f} 分钟（{percentage:.1f}%）', flush=True)
                        last_report = time.monotonic()
            if process.wait() != 0:
                raise ReplayError(f'视频保存失败；未完成文件会保留。详细日志：{error_log}')
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait()
            raise
        finally:
            process.stdout.close()
    return output_seconds


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_replay(session, link, output_root, inspect_only=False, proxy=None):
    params = parse_link(link)
    requested_seconds = int(params['end_time']) - int(params['start_time'])
    print(f'回放场次：{params["live_key"]}，链接时间范围：{requested_seconds / 60:.2f} 分钟。', flush=True)
    directory = Path(output_root).resolve() / ('full_' + params['live_key'])
    output = directory / 'replay.mp4'
    if output.exists():
        raise ReplayError(f'完整文件已存在，不会覆盖：{output}。需要重新下载时请指定另一个输出目录。')
    api = AUTHORIZED_API if 'live_uid' in params else API
    entry = select_stream(get_json(session, api, params))
    source_url, source_seconds, playlists = read_playlist(session, entry['stream'])
    print(f'取得一条完整视频流，播放列表总时长：{source_seconds / 60:.2f} 分钟。', flush=True)
    if requested_seconds - source_seconds > 30:
        raise ReplayError('视频流时长明显短于链接时间范围，无法确认整场完整性；已停止下载。')
    if inspect_only:
        return {'source_duration_seconds': source_seconds, 'stream_count': 1}
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    partial = directory / f'replay-{stamp}.partial.mp4'
    for index, playlist in enumerate(playlists):
        (directory / f'source-{index + 1}.m3u8').write_text(playlist, encoding='utf-8')
    headers = f'User-Agent: {USER_AGENT}\r\nReferer: https://live.bilibili.com/\r\n'
    print('正在原样保存整条视频流，不裁切、不拼接独立视频、不重编码。', flush=True)
    saved_seconds = run_ffmpeg([
        '-n', '-rw_timeout', '30000000', '-headers', headers, '-i', source_url,
        '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy', '-movflags', '+faststart',
        str(partial)], directory / f'download-{stamp}.log', source_seconds, proxy)
    print('下载完成，正在读取完整文件并核对时长……', flush=True)
    verified_seconds = run_ffmpeg([
        '-i', str(partial), '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy',
        '-f', 'null', '-'], directory / f'verify-{stamp}.log')
    if abs(verified_seconds - source_seconds) > 2:
        raise ReplayError('保存文件与完整播放列表时长相差超过2秒，文件保持未完成标记，请检查日志。')
    if not partial.exists() or partial.stat().st_size == 0:
        raise ReplayError('没有生成有效的视频文件。')
    metadata = {
        'live_key': params['live_key'], 'start_time': int(params['start_time']),
        'end_time': int(params['end_time']), 'source_duration_seconds': source_seconds,
        'saved_duration_seconds': saved_seconds, 'verified_duration_seconds': verified_seconds,
        'operation': 'single continuous source; stream copy; no cutting; no re-encoding',
        'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
        'sha256': sha256_file(partial), 'file_size': partial.stat().st_size,
        'source_start_time': entry.get('start_time'), 'source_end_time': entry.get('end_time'),
    }
    if 'live_uid' in params:
        metadata['live_uid'] = params['live_uid']
    (directory / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    if output.exists():
        raise ReplayError('另一下载任务已生成完整文件，本次未完成文件保留，不会覆盖。')
    partial.rename(output)
    print(f'完整视频已保存：{output}', flush=True)
    print(f'核对时长：{verified_seconds / 60:.2f} 分钟；来源播放列表和文件校验信息已一同保存。', flush=True)
    return output


def validate_proxy(value):
    address = urlsplit(value)
    if (address.scheme != 'http' or not address.hostname or address.query or address.fragment
            or address.path not in ('', '/')):
        raise argparse.ArgumentTypeError('代理格式应为 http://地址:端口，例如 http://127.0.0.1:7890')
    try:
        address.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError('代理端口无效。') from exc
    return value


def main(argv=None):
    from . import __version__

    parser = argparse.ArgumentParser(description='完整直播回放保存：不裁切、不重编码')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--link', action='append', help='回放剪辑页面链接，可多次传入以复用一次登录')
    parser.add_argument('--output', type=Path, default=Path.cwd() / 'downloads', help='输出目录，默认 downloads')
    parser.add_argument('--proxy', type=validate_proxy, help='可选的 HTTP 代理地址；默认直连')
    parser.add_argument('--no-open-qr', action='store_true', help='只显示二维码文件路径，不自动打开图片')
    parser.add_argument('--inspect-only', action='store_true', help='登录并检查完整视频流，暂不下载')
    options = parser.parse_args(argv)
    try:
        links = options.link or [input('请输入直播回放剪辑页面链接：').strip()]
        for link in links:
            params = parse_link(link)
            destination = options.output / ('full_' + params['live_key']) / 'replay.mp4'
            if destination.exists():
                raise ReplayError(f'完整文件已存在：{destination}。需要重新下载时请指定另一个输出目录。')
        runtime = Path.cwd() / '.runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        with requests.Session() as session, tempfile.TemporaryDirectory(dir=runtime) as temporary:
            session.trust_env = False
            session.headers.update({'User-Agent': USER_AGENT, 'Referer': 'https://live.bilibili.com/'})
            if options.proxy:
                session.proxies.update({'http': options.proxy, 'https': options.proxy})
            login(session, Path(temporary) / 'login.png', not options.no_open_qr)
            for index, link in enumerate(links, 1):
                if len(links) > 1:
                    print(f'正在处理第 {index}/{len(links)} 场回放。', flush=True)
                save_replay(session, link, options.output, options.inspect_only, options.proxy)
    except (ReplayError, requests.RequestException, ValueError, OSError) as exc:
        # RequestException URLs can contain session tokens; report only its type.
        detail = type(exc).__name__ if isinstance(exc, requests.RequestException) else str(exc)
        print(f'未完成：{detail}', flush=True)
        return 1
    except KeyboardInterrupt:
        print('已停止。未完成的视频文件会保留。', flush=True)
        return 130
    except EOFError:
        print('未收到回放链接。请用 --link 参数传入链接，或在交互窗口运行。', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
