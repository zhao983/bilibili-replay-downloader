# Bilibili Replay Downloader

输入直播回放链接，使用手机 B 站 App 扫码登录，把有权访问的完整直播回放保存为 MP4。

适用于当前的直播回放剪辑页面 `/web-cut/quick-publish.html`、`/web-cut/quick-publish-mobile.html` 和 `/web-cut/index.html`。支持自己的不同场次回放；带 `anchor_id` 的链接走主播授权接口，实际权限由 B 站验证。

程序直接保存一条完整、已结束的视频流，没有本地两小时时长上限。保存使用 FFmpeg stream copy，不裁切、不重编码，也不自动拼接独立短片。HLS 本身通过网络数据块传输，读取这些数据块是播放和保存同一条视频流的正常过程。

## 快速开始（Windows）

需要先安装 **Python 3.10 或更新版本**，并让 `python` 可以在终端中运行。

1. 下载并解压项目，或克隆仓库。
2. 双击 `start.cmd`。首次运行会建立项目独立环境并安装依赖。
3. 粘贴自己的直播回放剪辑页面链接，按回车。
4. 用手机 **B 站 App** 扫描自动打开的二维码，在手机上确认登录。
5. 等待保存和时长检查完成。文件位于 `downloads/full_场次编号/replay.mp4`。

从 [直播中心的直播回放列表] 找到目标场次，打开“投片段”或剪辑页面，复制地址栏的完整链接。程序不会投稿视频。

链接必须包含 `live_key`、`start_time`、`end_time`。示例格式如下，数字是演示值，不能用于实际下载：

```text
https://live.bilibili.com/web-cut/quick-publish.html?start_time=1000000000&end_time=1000010358&live_key=123456789012345678
```

当前不支持普通直播间链接、BV 视频链接或旧版 `/record/R...` 链接。

## 手动安装与运行

### Windows PowerShell

在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m bilibili_replay_downloader
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
bili-replay
```

FFmpeg 由 `imageio-ffmpeg` 依赖查找；该库在支持的平台上提供 FFmpeg 安装包，通常无需另外安装。在没有对应安装包的平台，可安装 FFmpeg 并设置 `IMAGEIO_FFMPEG_EXE` 指向其路径。完整回放实测在 Windows / Python 3.10 上完成，macOS 和 Linux 未做实机登录下载验证。

## 命令行选项

以下命令在已激活的独立环境中运行；Windows 也可以使用 `.venv\Scripts\bili-replay.exe`。

```bash
# 使用链接下载
bili-replay --link "你的完整回放链接"

# 选择保存目录
bili-replay --link "你的完整回放链接" --output "D:/我的回放"

# 多个不同场次复用一次扫码登录，按顺序保存
bili-replay --link "第一场回放链接" --link "第二场回放链接"

# 登录后只检查视频流，不下载
bili-replay --link "你的完整回放链接" --inspect-only

# 默认直连；需要代理时显式指定 HTTP 代理
bili-replay --link "你的完整回放链接" --proxy "http://127.0.0.1:7890"

# 不自动打开二维码，按终端中的路径手动打开
bili-replay --no-open-qr
```

二维码通常约三分钟过期，过期后重新运行即可。不同回放需要仍在有效期内，并且当前登录账号拥有播放/剪辑权限。带 `anchor_id` 的授权回放接口已做离线测试，尚未使用真实授权账号下载验证。

## 完整性与输出

每场回放使用独立目录：

```text
downloads/full_场次编号/
├── replay.mp4           # 下载及检查通过的完整文件
├── metadata.json        # 来源/保存时长、下载时间、文件 SHA-256 等
├── source-1.m3u8        # 来源播放列表；可能有多个层级的列表
├── download-*.log       # 保存日志
└── verify-*.log         # 完整文件读取检查日志
```

- 保存一条视频流中的第一条视频轨和第一条音频轨（如果存在）。
- 要求完整 HLS 播放列表包含结束标记；选择最高带宽的可用视频版本。
- 视频流时长比链接时间范围短超过 30 秒时停止，避免把明显缺失的回放报成完整。
- 来源播放列表与保存文件的时长相差超过 2 秒时，检查不通过。
- 已有 `replay.mp4` 不会被覆盖。需要重新下载时指定其他输出目录。
- 网络中断、退出或检查失败时保留 `.partial.mp4`；当前版本重新下载会从头开始，不支持断点续传。
- 平台返回多条独立视频流时停止，不自动拼接。原始直播中的停播、卡顿和时间戳异常不会由工具补画面或修复。

时长和哈希记录用于核对来源及保存文件，不能单独证明挑战录像符合组织方全部要求。MP4 封装后的文件哈希也不等同于网络传输数据块的哈希。

## 登录与数据

扫码请求通过 B 站官方 `passport.bilibili.com` 接口发起，二维码指向 B 站登录域名。用户在手机 App 上确认登录；程序不要求输入账号密码。登录信息只保存在本次运行的内存中。

Cookie 只保存在本次进程内存中，结束后不保留。临时二维码在退出时清理。默认直连，不修改系统代理设置，保留 HTTPS 证书验证。FFmpeg 日志中的完整 URL 会被隐藏。

来源播放列表可能含有临时签名的视频链接；下载的视频、日志、播放列表、校验信息和二维码都是本地运行数据。`.gitignore` 和源码打包脚本会排除这些数据，上传 GitHub 时使用源码项目或生成的源码 ZIP。

## 常见问题

**链接在网页能看，程序提示未登录或没有权限？**

程序的登录会话独立于浏览器。请用拥有该场回放权限的账号扫码；网页链接本身不携带访问权限。

**安装时出现 `SSLEOFError / ProxyError`？**

`setup.cmd` 会先正常安装，失败后尝试仅在安装进程内直连。PowerShell 手动安装时可以临时绕过代理：

```powershell
$previousNoProxy = $env:NO_PROXY
try {
    $env:NO_PROXY = '*'
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install .
} finally {
    $env:NO_PROXY = $previousNoProxy
}
```

运行时默认直连；若网络必须使用代理，则用 `--proxy http://地址:端口` 明确配置。HTTPS 目标网站通常也通过 HTTP 代理的 CONNECT 隧道连接，所以本地代理示例使用 `http://127.0.0.1:7890`。

**超过两小时一定能下载吗？**

工具没有两小时限制，曾保存约 172 分钟的一条完整回放。能否下载取决于 B 站实际返回的视频流、权限、回放有效期及网络。B 站当前接口可能变化，不保证所有场次都能下载。

**为什么录像时长比链接里的起止时间短几秒？**

直播场次时间范围与平台实际录制的视频流可能不同。程序记录两者的时长，并检查最终文件是否包含所取得的完整流。

## 开发与测试

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试不需要 B 站账号，不会联网登录或下载私人回放。覆盖链接解析、扫码状态、权限接口选择、完整播放列表检查、异常时保留未完成文件，以及实际 FFmpeg 保存后逐帧一致性。GitHub Actions 配置了 Windows / Linux、Python 3.10 / 3.12 的测试矩阵；本地交付验证在 Windows / Python 3.10 执行。

脚本使用允许列表，仅打包源码、测试、文档、许可证、启动脚本和 CI 配置。

## 实现与参考

扫码登录 → 根据链接请求自己的 `GetSliceStream` 或授权主播的 `GetUserSliceStream` → 检查完整播放列表 → FFmpeg `-c copy` 保存 → 读取完整文件并核对时长 → 生成 SHA-256 记录。

接口行为参考 [bilibili-API-collect 的直播回放说明](https://github.com/pskdje/bilibili-API-collect/blob/main/docs/live/live_replay.md)和[二维码登录说明](https://github.com/pskdje/bilibili-API-collect/blob/main/docs/login/login_action/QR.md)。开发背景来自对 [Buyi-wsgzg/bilibili-live-records](https://github.com/Buyi-wsgzg/bilibili-live-records)旧项目的运行排查；本项目使用本次编写的完整回放实现，不包含旧项目的 MoviePy 下载与转码代码。

本项目不是 B 站官方工具。请用于自己或已获授权的回放。项目源码采用 [MIT License](LICENSE)，第三方依赖和 FFmpeg 按其各自许可证分发。
