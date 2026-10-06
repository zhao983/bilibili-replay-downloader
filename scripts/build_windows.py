"""Build a single Windows EXE with Python, Tk, TLS certificates and FFmpeg."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.name != 'nt':
        raise SystemExit('Build this Windows executable on Windows.')
    assets = ROOT / 'build' / 'desktop-assets'
    licenses = assets / 'licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    names = ('requests', 'imageio-ffmpeg', 'qrcode', 'pillow', 'certifi',
             'charset-normalizer', 'idna', 'urllib3', 'pyinstaller')
    inventory = []
    for name in names:
        distribution = importlib.metadata.distribution(name)
        inventory.append(f'{name} {distribution.version}')
        for item in distribution.files or ():
            if any(part.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')) for part in item.parts):
                target = licenses / name / str(item).replace('../', '').replace('..\\', '')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(Path(distribution.locate_file(item)).read_bytes())
    # Preserve the Python/Tcl/Tk license texts distributed with the runtime.
    for folder, prefix in ((Path(sys.base_prefix), 'python'), (Path(sys.base_prefix) / 'tcl', 'tcl-tk')):
        candidates = folder.glob('*LICENSE*') if prefix == 'python' else folder.rglob('license.terms')
        for item in candidates:
            target = licenses / prefix / item.relative_to(folder)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
    executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if executable.parent.name != 'binaries':
        raise SystemExit('Use the FFmpeg binary shipped in the imageio-ffmpeg wheel for a reproducible build.')
    license_output = subprocess.run([str(executable), '-L'], capture_output=True, text=True, check=True)
    (licenses / 'ffmpeg-build-and-license.txt').write_text(license_output.stderr + license_output.stdout, encoding='utf-8')
    notices = ROOT / 'THIRD_PARTY_NOTICES.md'
    if not (ROOT / 'licenses' / 'GPL-3.0.txt').exists():
        raise SystemExit('Missing licenses/GPL-3.0.txt')
    icon = assets / 'app.ico'
    picture = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((8, 8, 248, 248), radius=52, fill='#1677d2')
    draw.rounded_rectangle((46, 58, 210, 184), radius=22, outline='white', width=12)
    draw.polygon(((103, 89), (103, 153), (160, 121)), fill='white')
    draw.line(((94, 210), (162, 210)), fill='white', width=12)
    picture.save(icon, sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
               '--noupx', '--name', 'BiliReplayDownloader', '--paths', str(ROOT / 'src'),
               '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build' / 'pyinstaller'),
               '--specpath', str(ROOT / 'build'), '--icon', str(icon),
               '--collect-data', 'certifi', '--hidden-import', 'PIL._tkinter_finder',
               '--add-binary', f'{executable}:imageio_ffmpeg/binaries',
               '--add-data', f'{ROOT / "LICENSE"}:licenses',
               '--add-data', f'{ROOT / "licenses"}:licenses',
               '--add-data', f'{licenses}:licenses/dependencies',
               '--add-data', f'{notices}:.', str(ROOT / 'scripts' / 'desktop_entry.py')]
    subprocess.run(command, cwd=ROOT, check=True)
    result = ROOT / 'dist' / 'BiliReplayDownloader.exe'
    digest = hashlib.sha256(result.read_bytes()).hexdigest()
    (ROOT / 'dist' / 'SHA256SUMS.txt').write_text(f'{digest}  {result.name}\n', encoding='utf-8')
    (ROOT / 'dist' / 'build-info.json').write_text(json.dumps({'python': sys.version,
           'dependencies': inventory, 'bytes': result.stat().st_size, 'sha256': digest}, indent=2), encoding='utf-8')
    print(f'EXE: {result}\nSHA256: {digest}')


if __name__ == '__main__':
    main()
