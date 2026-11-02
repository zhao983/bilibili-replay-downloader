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
    BG = '#f5f6fa'
    INK = '#17283e'
    MUTED = '#65758b'
    BLUE = '#6655dc'

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
        self.task_outcome = None
        root.title(f'B站完整回放下载器 · {__version__}')
        root.geometry('1080x760')
        root.minsize(min(1040, max(900, root.winfo_screenwidth() - 60)),
                     min(740, max(620, root.winfo_screenheight() - 90)))
        root.configure(bg=self.BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        from .desktop_view import build
        build(self)
        root.update_idletasks()
        width = min(max(1080, root.winfo_reqwidth()), root.winfo_screenwidth() - 60)
        height = max(760, root.winfo_reqheight())
        root.geometry(f'{width}x{height}')
        root.after(100, self.fit_window)
        self.poll_id = root.after(100, self.poll)

    def fit_window(self):
        self.root.update_idletasks()
        desired = self.main_content.winfo_reqheight() + 52
        height = min(max(780, desired), self.root.winfo_screenheight() - 90)
        self.root.geometry(f'{self.root.winfo_width()}x{height}')

    def choose_folder(self):
        result = filedialog.askdirectory(title='选择视频保存文件夹', parent=self.root)
        if result:
            self.folder.set(result)

    def paste_link(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            self.status.set('剪贴板里还没有链接，请先复制回放页面的网址。')
            return
        if not text:
            self.status.set('剪贴板是空的，请先复制回放页面的网址。')
            return
        self.link.delete('1.0', 'end')
        self.link.insert('1.0', text)
        self.link.focus_set()
        self.status.set('已粘贴链接。选择保存位置后，即可开始下载。')

    def toggle_details(self):
        self.details_visible = not self.details_visible
        if self.details_visible:
            self.details_panel.pack(fill='both', expand=True, pady=(8, 0))
            self.details_button.configure(text='收起任务详情  ▴')
            self.root.update_idletasks()
            needed = min(self.main_content.winfo_reqheight() + 52, self.root.winfo_screenheight() - 90)
            if self.root.winfo_height() < needed:
                self.root.geometry(f'{self.root.winfo_width()}x{needed}')
        else:
            self.details_panel.pack_forget()
            self.details_button.configure(text='查看任务详情  ▾')

    def account_state(self, logged_in=False, loading=False):
        self.auth_badge.configure(text='已登录' if logged_in else ('登录中' if loading else '未登录'),
                                  fg='#387c67' if logged_in else ('#6655dc' if loading else '#8c94a4'),
                                  bg='#eaf6f0' if logged_in else ('#efedfc' if loading else '#f0f2f6'))

    def task_state(self, title, indicator, color='#6655dc'):
        self.task_title.configure(text=title)
        self.percent.set(indicator)
        self.percent_label.configure(fg=color)

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
                       self.folder_entry, self.network_button, self.paste_button):
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
        self.task_outcome = None
        self.progress['value'] = 0
        self.status.set('正在准备……')
        self.task_state('正在准备', '请稍候')
        self.set_busy(True)

    def cancel(self):
        self.controller.cancel()
        self.cancel_button.configure(state='disabled')
        self.status.set('正在停止，请稍候。未完成的视频文件会保留。')
        self.task_state('正在停止', '请稍候', '#b48936')

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
            self.qr_label.configure(image=self.qr_photo, text='', bg='white')
            self.account.set('请扫码并在手机上确认')
            self.account_state(loading=True)
        elif kind in ('logged_in', 'logged_out'):
            self.account.set('已登录 · 本次运行有效' if kind == 'logged_in' else '尚未登录')
            self.qr_label.configure(image='', text='✓\n\n登录成功\n可以下载不同场次的回放' if kind == 'logged_in' else '点击下方按钮\n获取新的登录二维码',
                                    fg='#3d8272' if kind == 'logged_in' else '#8f97b2', bg='#f1f8f6' if kind == 'logged_in' else '#f8f9fc')
            self.qr_photo = None
            self.account_state(logged_in=kind == 'logged_in')
            self.login_button.configure(text='重新扫码登录' if kind == 'logged_in' else '扫码登录')
            if kind == 'logged_in':
                self.status.set('登录成功，可以开始下载。')
        elif kind == 'phase':
            self.phase = data['phase']
            phases = {'login': ('等待扫码登录', '手机确认'), 'download': ('正在下载回放', '0.0%'),
                      'verify': ('正在检查完整性', '即将完成'), 'hash': ('正在生成校验记录', '即将完成')}
            self.task_state(*phases.get(self.phase, ('正在处理', '请稍候')))
            self.progress.stop()
            self.progress.configure(mode='determinate' if self.phase == 'download' else 'indeterminate')
            if self.phase != 'download':
                self.progress.start(15)
            if self.phase == 'login':
                self.account.set('正在生成二维码……')
                self.account_state(loading=True)
                self.qr_label.configure(image='', text='正在获取二维码…', fg='#8f97b2', bg='#f8f9fc')
                self.qr_photo = None
        elif kind == 'status':
            self.status.set(data['message'])
            self.log(data['message'])
        elif kind == 'progress' and self.phase == 'download' and data.get('total'):
            percent = min(99, data['seconds'] / data['total'] * 100)
            self.progress['value'] = percent
            self.percent.set(f'{percent:.1f}%')
            self.status.set(f"正在下载：{percent:.1f}% · 已保存 {data['seconds'] / 60:.1f} / {data['total'] / 60:.1f} 分钟")
        elif kind == 'complete':
            self.task_outcome = 'complete'
            self.output_file = Path(data['path'])
            self.progress.stop()
            self.progress.configure(mode='determinate', value=100)
            self.status.set('下载完成，完整性检查已通过。点击“打开保存文件夹”查看视频。')
            self.task_state('回放已完整保存', '100%  完成', '#3d8272')
            self.log(f'视频位置：{self.output_file}')
        elif kind in ('error', 'cancelled'):
            self.task_outcome = kind
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.status.set('任务未完成，请查看提示后重试。' if kind == 'error' else '已停止。未完成的视频文件会保留。')
            self.task_state('下载未完成' if kind == 'error' else '任务已停止', '可重试', '#ba6571' if kind == 'error' else '#b48936')
            self.log(data['message'])
            if not self.controller.session:
                self.qr_label.configure(image='', text='点击下方按钮\n获取新的登录二维码', fg='#8f97b2', bg='#f8f9fc')
                self.qr_photo = None
                self.account.set('尚未登录')
                self.account_state()
            if kind == 'error' and not self.closing:
                messagebox.showerror('任务未完成', data['message'][-2600:], parent=self.root)
        elif kind == 'finished':
            self.progress.stop()
            self.progress.configure(mode='determinate', value=100 if self.output_file else 0)
            if (self.phase == 'login' and self.controller.session is not None
                    and not self.output_file and self.task_outcome is None):
                self.task_state('准备下载', '已登录', '#3d8272')
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
