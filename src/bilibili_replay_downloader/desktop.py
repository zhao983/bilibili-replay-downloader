"""Windows desktop UI. All network and video work stays off the Tk thread."""
import argparse
import io
import os
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from PIL import Image, ImageTk
import requests

from . import __version__
from . import downloader as core


class DesktopController:
    def __init__(self, callback):
        self.callback = callback
        self.session = None
        self.control = None
        self.worker = None
        self.session_factory = requests.Session

    @property
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def _login(self, proxy):
        if self.session:
            self.session.close()
            self.session = None
        session = self.session_factory()
        session.trust_env = False
        session.headers.update({'User-Agent': core.USER_AGENT, 'Referer': 'https://live.bilibili.com/'})
        if proxy:
            session.proxies.update({'http': proxy, 'https': proxy})
        try:
            with tempfile.TemporaryDirectory(prefix='bili-replay-login-') as directory:
                core.login(session, Path(directory) / 'login.png', False, control=self.control)
            self.control.check()
            self.session = session
        except BaseException:
            session.close()
            raise

    def start(self, action, link='', folder=None, proxy=None):
        if self.busy:
            raise core.ReplayError('已有任务正在进行。')
        if action == 'download':
            values = core.parse_link(link)
            folder = Path(folder).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            # Check permissions before asking the user to scan a QR code.
            with tempfile.TemporaryFile(dir=folder):
                pass
            output = folder / ('full_' + values['live_key']) / 'replay.mp4'
            if output.exists():
                raise core.ReplayError('这个位置已经有完整回放，请选择其他保存文件夹。')
        if proxy:
            proxy = core.validate_proxy(proxy)
        self.control = core.TaskControl(self.callback)
        def work():
            try:
                if action == 'login' or self.session is None:
                    self.callback('phase', {'phase': 'login'})
                    self._login(proxy)
                if action == 'download':
                    result = core.save_replay(self.session, link, folder, proxy=proxy, control=self.control)
                    self.callback('complete', {'path': str(result)})
            except core.CancelledError as exc:
                self.callback('cancelled', {'message': str(exc)})
            except Exception as exc:
                if isinstance(exc, requests.RequestException):
                    detail = '网络连接失败，请检查网络后重试。如需代理，可在“网络设置”中填写。'
                elif isinstance(exc, (core.ReplayError, OSError, ValueError, argparse.ArgumentTypeError)):
                    detail = str(exc)
                else:
                    detail = f'任务未完成（{type(exc).__name__}），请重新尝试。'
                if '登录会话无效' in detail and self.session:
                    self.session.close()
                    self.session = None
                    self.callback('logged_out', {})
                self.callback('error', {'message': detail})
            finally:
                self.callback('finished', {})
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def cancel(self):
        if self.control:
            self.control.cancelled.set()

    def close(self):
        if self.busy:
            raise core.ReplayError('请先停止当前任务。')
        if self.session:
            self.session.close()
            self.session = None


class ReplayWindow:
    BG = '#f3f6fb'
    INK = '#17283e'
    MUTED = '#65758b'
    BLUE = '#1677d2'

    def __init__(self, root):
        # Use a compact baseline, then size the window to its actual contents.
        root.tk.call('tk', 'scaling', min(float(root.tk.call('tk', 'scaling')), 4 / 3))
        self.root = root
        self.events = queue.Queue()
        self.controller = DesktopController(lambda kind, data: self.events.put((kind, data)))
        self.output_file = None
        self.phase = 'idle'
        self.closing = False
        self.qr_photo = None
        root.title(f'B站完整回放下载器 · {__version__}')
        root.geometry('960x710')
        root.minsize(880, 680)
        root.configure(bg=self.BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background=self.BG)
        style.configure('Card.TFrame', background='white')
        style.configure('TLabel', background=self.BG, foreground=self.INK)
        style.configure('Card.TLabel', background='white', foreground=self.INK)
        style.configure('Muted.TLabel', foreground=self.MUTED)
        style.configure('TButton', padding=(14, 8))
        style.configure('Primary.TButton', background=self.BLUE, foreground='white', borderwidth=0)
        style.map('Primary.TButton', background=[('active', '#0d63b2'), ('disabled', '#b9cce0')],
                  foreground=[('disabled', 'white')])
        style.configure('TEntry', padding=7)
        style.configure('TProgressbar', background=self.BLUE, troughcolor='#e4edf7', borderwidth=0)
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='把整场回放，完整留下', font=('Microsoft YaHei UI', 23, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='粘贴链接  →  手机扫码  →  保存为 MP4', style='Muted.TLabel').pack(anchor='w', pady=(5, 18))
        body = ttk.Frame(outer)
        body.pack(fill='x')
        body.columnconfigure(0, weight=1)
        left = ttk.Frame(body, style='Card.TFrame', padding=20)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text='1  填写直播回放链接', style='Card.TLabel', font=('Microsoft YaHei UI', 12, 'bold')).grid(row=0, column=0, sticky='w')
        self.link = tk.Text(left, height=3, wrap='char', font=('Microsoft YaHei UI', 10),
                            relief='solid', bd=1, highlightthickness=0, padx=9, pady=9,
                            fg=self.INK, bg='#fafcff', width=48)
        self.link.grid(row=1, column=0, sticky='ew', pady=(12, 8))
        ttk.Label(left, text='直播中心 → 直播回放 → 投片段，复制地址栏链接',
                  style='Card.TLabel', foreground=self.MUTED, font=('Microsoft YaHei UI', 9)).grid(row=2, column=0, sticky='w')
        ttk.Button(left, text='打开 B 站直播中心', command=lambda: webbrowser.open('https://link.bilibili.com/#/my-room/live-record')).grid(row=3, column=0, sticky='w', pady=(8, 20))
        ttk.Label(left, text='2  选择保存位置', style='Card.TLabel', font=('Microsoft YaHei UI', 12, 'bold')).grid(row=4, column=0, sticky='w')
        folder_row = ttk.Frame(left, style='Card.TFrame')
        folder_row.grid(row=5, column=0, sticky='ew', pady=(12, 6))
        folder_row.columnconfigure(0, weight=1)
        self.folder = tk.StringVar(value=str(Path.home() / 'Videos' / 'B站直播回放'))
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder)
        self.folder_entry.grid(row=0, column=0, sticky='ew')
        self.choose_button = ttk.Button(folder_row, text='浏览…', command=self.choose_folder)
        self.choose_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(left, text='每场回放保存在单独文件夹，已有视频不会被覆盖。',
                  style='Card.TLabel', foreground=self.MUTED, font=('Microsoft YaHei UI', 9)).grid(row=6, column=0, sticky='w')
        right = ttk.Frame(body, style='Card.TFrame', padding=18, width=275)
        right.grid(row=0, column=1, sticky='nsew')
        ttk.Label(right, text='3  B 站 App 扫码登录', style='Card.TLabel', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        self.qr_label = tk.Label(right, text='点击下方“扫码登录”\n二维码会显示在这里',
                                 bg='#f2f6fc', fg=self.MUTED, width=28, height=10,
                                 font=('Microsoft YaHei UI', 10), relief='flat')
        self.qr_label.pack(pady=(14, 10), fill='x')
        self.account = tk.StringVar(value='尚未登录')
        ttk.Label(right, textvariable=self.account, style='Card.TLabel').pack()
        self.login_button = ttk.Button(right, text='扫码登录', command=lambda: self.begin('login'))
        self.login_button.pack(pady=10, fill='x')
        ttk.Label(right, text='请在手机上确认登录\n关闭客户端后自动退出登录', style='Card.TLabel',
                  foreground=self.MUTED, justify='center', font=('Microsoft YaHei UI', 9)).pack()
        action = ttk.Frame(outer)
        action.pack(fill='x', pady=(18, 8))
        self.download_button = ttk.Button(action, text='开始下载完整回放', style='Primary.TButton', command=lambda: self.begin('download'))
        self.download_button.pack(side='left')
        self.cancel_button = ttk.Button(action, text='停止', state='disabled', command=self.cancel)
        self.cancel_button.pack(side='left', padx=10)
        self.open_button = ttk.Button(action, text='打开保存文件夹', command=self.open_folder)
        self.open_button.pack(side='right')
        self.status = tk.StringVar(value='准备就绪。填写链接并选择保存位置，未登录时会自动显示二维码。')
        ttk.Label(outer, textvariable=self.status, wraplength=865).pack(anchor='w', pady=(5, 9))
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.pack(fill='x')
        bottom = ttk.Frame(outer)
        bottom.pack(fill='x', pady=(12, 0))
        self.network_button = ttk.Button(bottom, text='网络设置', command=self.network_settings)
        self.network_button.pack(side='left')
        ttk.Button(bottom, text='使用帮助', command=self.help).pack(side='left', padx=8)
        ttk.Button(bottom, text='关于', command=self.about).pack(side='left')
        ttk.Label(bottom, text='完整保存 · 不裁切 · 不重新编码', style='Muted.TLabel').pack(side='right')
        self.proxy = ''
        self.details = tk.Text(outer, height=4, wrap='word', bg=self.BG, fg=self.MUTED,
                               relief='flat', font=('Microsoft YaHei UI', 9), state='disabled')
        self.details.pack(fill='both', expand=True, pady=(6, 0))
        root.update_idletasks()
        width = max(960, root.winfo_reqwidth())
        height = max(710, root.winfo_reqheight())
        root.geometry(f'{width}x{height}')
        self.poll_id = root.after(100, self.poll)

    def choose_folder(self):
        result = filedialog.askdirectory(title='选择视频保存文件夹', parent=self.root)
        if result:
            self.folder.set(result)

    def open_folder(self):
        path = self.output_file.parent if self.output_file else Path(self.folder.get()).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(str(path.resolve()))
            else:
                webbrowser.open(path.resolve().as_uri())
        except OSError:
            messagebox.showerror('无法打开文件夹', '请检查保存位置是否可用。', parent=self.root)

    def help(self):
        messagebox.showinfo('如何下载', '1. 在 B 站直播中心找到目标回放，打开“投片段”，复制网页地址。\n\n'
                            '2. 粘贴完整地址，选择有足够空间的保存文件夹。\n\n'
                            '3. 点击开始下载，用手机 B 站 App 扫码，并确认登录。\n\n'
                            '4. 等待完整性检查完成，然后打开保存文件夹。\n\n'
                            '只支持账号有权访问的回放。停止或网络中断后会保留未完成文件；重新下载会从头开始。', parent=self.root)

    def about(self):
        import sys
        dialog = tk.Toplevel(self.root)
        dialog.title('关于与开源组件')
        dialog.geometry('720x510')
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f'B站完整回放下载器 {__version__}', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='非 B 站官方工具 · 项目源码采用 MIT 许可证').pack(anchor='w', pady=8)
        content = ttk.Frame(frame)
        content.pack(fill='both', expand=True)
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
        texts = [('组件说明', base / 'THIRD_PARTY_NOTICES.md')]
        texts.extend((path.name, path) for path in (base / 'licenses').rglob('*') if path.is_file())
        choices = tk.Listbox(content, width=24, exportselection=False)
        choices.pack(side='left', fill='y', padx=(0, 10))
        field = tk.Text(content, wrap='word', font=('Microsoft YaHei UI', 9))
        scroll = ttk.Scrollbar(content, command=field.yview)
        field.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        field.pack(fill='both', expand=True)
        for title, path in texts:
            choices.insert('end', title)
        def show_license(event=None):
            selected = choices.curselection()
            if selected:
                path = texts[selected[0]][1]
                field.configure(state='normal')
                field.delete('1.0', 'end')
                field.insert('end', path.read_text(encoding='utf-8', errors='replace') if path.exists() else '组件信息不可用。')
                field.configure(state='disabled')
        choices.bind('<<ListboxSelect>>', show_license)
        choices.selection_set(0)
        show_license()
        ttk.Button(frame, text='项目主页', command=lambda: webbrowser.open('https://github.com/zhao983/bilibili-replay-downloader')).pack(anchor='e', pady=8)

    def network_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('网络设置')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='通常保持空白即可。需要代理时填写 HTTP 代理地址。').pack(anchor='w')
        value = tk.StringVar(value=self.proxy)
        entry = ttk.Entry(frame, textvariable=value, width=49)
        entry.pack(fill='x', pady=12)
        ttk.Label(frame, text='例如：http://127.0.0.1:7890', style='Muted.TLabel').pack(anchor='w')
        def apply():
            proxy = value.get().strip()
            try:
                if proxy:
                    core.validate_proxy(proxy)
            except argparse.ArgumentTypeError as exc:
                messagebox.showerror('地址格式不正确', str(exc), parent=dialog)
                return
            # A session created under one proxy is never reused under another.
            if proxy != self.proxy:
                self.controller.close()
                self.event('logged_out', {})
                self.proxy = proxy
            dialog.destroy()
        ttk.Button(frame, text='保存', command=apply).pack(anchor='e', pady=(14, 0))
        dialog.grab_set()

    def set_busy(self, busy):
        state = 'disabled' if busy else 'normal'
        for widget in (self.login_button, self.download_button, self.choose_button,
                       self.folder_entry, self.network_button):
            widget.configure(state=state)
        self.link.configure(state=state)
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def begin(self, action):
        if self.controller.busy:
            return
        link = self.link.get('1.0', 'end').strip()
        folder = self.folder.get().strip()
        if action == 'download' and not folder:
            messagebox.showerror('请选择保存位置', '点击“浏览…”选择视频保存文件夹。', parent=self.root)
            return
        try:
            self.controller.start(action, link, folder, self.proxy or None)
        except (core.ReplayError, OSError, ValueError, argparse.ArgumentTypeError) as exc:
            messagebox.showerror('请检查填写的信息', str(exc), parent=self.root)
            return
        self.output_file = None
        self.progress['value'] = 0
        self.status.set('正在准备……')
        self.set_busy(True)

    def cancel(self):
        self.controller.cancel()
        self.cancel_button.configure(state='disabled')
        self.status.set('正在停止，请稍候。未完成的视频文件会保留。')

    def log(self, text):
        self.details.configure(state='normal')
        self.details.insert('end', text + '\n')
        if int(self.details.index('end-1c').split('.')[0]) > 120:
            self.details.delete('1.0', '30.0')
        self.details.see('end')
        self.details.configure(state='disabled')

    def event(self, kind, data):
        if kind == 'qr':
            image = Image.open(io.BytesIO(data['image'])).convert('RGB').resize((208, 208), Image.Resampling.NEAREST)
            self.qr_photo = ImageTk.PhotoImage(image, master=self.root)
            self.qr_label.configure(image=self.qr_photo, text='', width=208, height=208)
            self.account.set('请扫码并在手机上确认')
        elif kind in ('logged_in', 'logged_out'):
            self.account.set('已登录 · 本次运行有效' if kind == 'logged_in' else '尚未登录')
            self.qr_label.configure(image='', text='登录成功\n可以下载不同场次的回放' if kind == 'logged_in' else '请重新扫码登录', width=28, height=10)
            self.qr_photo = None
            self.login_button.configure(text='重新扫码登录' if kind == 'logged_in' else '扫码登录')
            if kind == 'logged_in':
                self.status.set('登录成功，可以开始下载。')
        elif kind == 'phase':
            self.phase = data['phase']
            self.progress.stop()
            self.progress.configure(mode='determinate' if self.phase == 'download' else 'indeterminate')
            if self.phase != 'download':
                self.progress.start(15)
            if self.phase == 'login':
                self.account.set('正在生成二维码……')
        elif kind == 'status':
            self.status.set(data['message'])
            self.log(data['message'])
        elif kind == 'progress' and self.phase == 'download' and data.get('total'):
            percent = min(99, data['seconds'] / data['total'] * 100)
            self.progress['value'] = percent
            self.status.set(f"正在下载：{percent:.1f}% · 已保存 {data['seconds'] / 60:.1f} / {data['total'] / 60:.1f} 分钟")
        elif kind == 'complete':
            self.output_file = Path(data['path'])
            self.progress.stop()
            self.progress.configure(mode='determinate', value=100)
            self.status.set('下载完成，完整性检查已通过。点击“打开保存文件夹”查看视频。')
            self.log(f'视频位置：{self.output_file}')
        elif kind in ('error', 'cancelled'):
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.status.set('任务未完成，请查看提示后重试。' if kind == 'error' else '已停止。未完成的视频文件会保留。')
            self.log(data['message'])
            if not self.controller.session:
                self.qr_label.configure(image='', text='点击“扫码登录”\n生成新的二维码', width=28, height=10)
                self.qr_photo = None
                self.account.set('尚未登录')
            if kind == 'error' and not self.closing:
                messagebox.showerror('任务未完成', data['message'][-2600:], parent=self.root)
        elif kind == 'finished':
            self.progress.stop()
            self.progress.configure(mode='determinate', value=100 if self.output_file else 0)
            self.set_busy(False)

    def poll(self):
        try:
            while True:
                self.event(*self.events.get_nowait())
        except queue.Empty:
            pass
        if self.closing and not self.controller.busy:
            self.controller.close()
            self.root.destroy()
            return
        self.poll_id = self.root.after(100, self.poll)

    def close(self):
        if self.controller.busy:
            if not messagebox.askyesno('退出客户端', '下载尚未结束。停止任务并退出？未完成文件会保留。', parent=self.root):
                return
            self.closing = True
            self.cancel()
            self.set_busy(True)
        else:
            self.controller.close()
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description='B站完整回放下载器客户端')
    parser.add_argument('--self-test', type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if os.name == 'nt':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    window = ReplayWindow(root)
    if options.self_test:
        from .desktop_check import run_check
        root.after(300, lambda: run_check(window, options.self_test))
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
