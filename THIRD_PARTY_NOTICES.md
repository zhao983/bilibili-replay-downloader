# Third-party components in the Windows desktop executable

The application source is under the MIT License (see LICENSE). The executable
also contains separately licensed components. Their license texts are included
inside the executable under `licenses/`, and extracted to the temporary bundle
directory while it runs. No component's license is replaced by the app's MIT
license.

- Python: PSF License, https://www.python.org/downloads/source/
- Tcl/Tk: Tcl/Tk license, https://www.tcl-lang.org/software/tcltk/
- Requests: Apache-2.0, https://github.com/psf/requests
- imageio-ffmpeg: BSD-2-Clause, https://github.com/imageio/imageio-ffmpeg
- qrcode: BSD, https://github.com/lincolnloop/python-qrcode
- Pillow: HPND and included third-party notices, https://github.com/python-pillow/Pillow
- certifi: MPL-2.0, https://github.com/certifi/python-certifi
- charset-normalizer, idna, urllib3: their included permissive license texts
- PyInstaller bootloader: GPL with the PyInstaller distribution exception,
  https://pyinstaller.org/en/stable/license.html

## FFmpeg

The Windows FFmpeg 7.1 executable is the unmodified binary from the
imageio-ffmpeg 0.6.0 Windows wheel, originally built by Gyan Doshi. It runs as a
separate subprocess. This build is GPL-3.0-or-later; see `licenses/GPL-3.0.txt`.
The exact version, build configuration, copyright and `ffmpeg -L` output are
captured by the build script inside `licenses/dependencies/ffmpeg-build-and-license.txt`.

Upstream source and build references:

- FFmpeg source: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz
- Binary provider and source-code information: https://www.gyan.dev/ffmpeg/builds/
- Upstream build scripts: https://github.com/gyan-dev/ffmpeg-builds
- FFmpeg licensing: https://ffmpeg.org/legal.html

When redistributing a binary, retain these notices and provide the corresponding
source access required by each component's license, including the linked FFmpeg
source and its build dependencies. Runtime build details and source references
can also be viewed from the desktop application's component information window.
