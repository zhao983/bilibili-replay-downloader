"""Desktop presentation, kept separate from login and download work."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import webbrowser

BG = '#f5f6fa'
INK = '#19243b'
MUTED = '#8791a5'
ACCENT = '#6655dc'
NAVY = '#1c2339'
BORDER = '#e7eaf2'
FONT = 'Microsoft YaHei UI'


class Card(tk.Canvas):
    """A rounded container whose height follows its native child widgets."""
    def __init__(self, parent, padding=22):
        super().__init__(parent, bg=BG, bd=0, highlightthickness=0, height=100, width=100)
        self.padding = padding
        self.body = tk.Frame(self, bg='white')
        self.window = self.create_window(padding, padding, anchor='nw', window=self.body)
        self.bind('<Configure>', self.layout)
        self.body.bind('<Configure>', self.layout)

    def layout(self, event=None):
        width, height, r = self.winfo_width(), self.winfo_height(), 16
        self.itemconfigure(self.window, width=max(1, width - self.padding * 2))
        desired = self.body.winfo_reqheight() + self.padding * 2
        if int(float(self['height'])) != desired:
            self.configure(height=desired)
        self.delete('surface')
        points = [r, 1, width-r, 1, width-1, 1, width-1, r,
                  width-1, height-r, width-1, height-1, width-r, height-1,
                  r, height-1, 1, height-1, 1, height-r, 1, r, 1, 1]
        self.create_polygon(points, smooth=True, splinesteps=24, fill='white',
                            outline=BORDER, tags='surface')
        self.tag_lower('surface')


def label(parent, text='', size=10, color=INK, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent['bg'], fg=color,
                    font=(FONT, size, 'bold' if bold else 'normal'), **kwargs)


def section(parent, number, title, caption):
    row = tk.Frame(parent, bg='white')
    row.pack(fill='x')
    badge = tk.Label(row, text=number, font=(FONT, 10, 'bold'), fg=ACCENT,
                     bg='#efedfc', width=3, pady=4)
    badge.pack(side='left', padx=(0, 10))
    label(row, title, size=12, bold=True).pack(side='left')
    label(parent, caption, size=9, color=MUTED, anchor='w').pack(fill='x', pady=(10, 12))


def build(window):
    w, root = window, window.root
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=(FONT, 10))
    style.configure('TFrame', background=BG)
    style.configure('TLabel', background=BG, foreground=INK)
    style.configure('TButton', padding=(14, 9), background='#eef0f7', foreground=INK,
                    borderwidth=0, relief='flat', focusthickness=0)
    style.map('TButton', background=[('disabled', '#f1f2f6'), ('active', '#e4e5ef')],
              foreground=[('disabled', '#a8aebe')])
    style.configure('Primary.TButton', background=ACCENT, foreground='white', padding=(22, 12))
    style.map('Primary.TButton', background=[('disabled', '#c5bfeb'), ('active', '#5543c6')],
              foreground=[('disabled', '#f8f7ff')])
    style.configure('Soft.TButton', background='#efedfc', foreground=ACCENT)
    style.map('Soft.TButton', background=[('disabled', '#f3f2f8'), ('active', '#e6e1ff')])
    style.configure('Link.TButton', background='white', foreground=ACCENT, padding=(0, 4))
    style.map('Link.TButton', background=[('active', 'white')], foreground=[('active', '#4631bf')])
    style.configure('Nav.TButton', background=NAVY, foreground='#c1c8dc', padding=(14, 10), anchor='w')
    style.map('Nav.TButton', background=[('active', '#2b344f'), ('disabled', NAVY)],
              foreground=[('disabled', '#626d89')])
    style.configure('TEntry', padding=10, fieldbackground='#f8f9fc', foreground=INK,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
    style.map('TEntry', bordercolor=[('focus', '#a99ded')])
    style.configure('TProgressbar', background=ACCENT, troughcolor='#eeedf7',
                    borderwidth=0, thickness=7, lightcolor=ACCENT, darkcolor=ACCENT,
                    bordercolor='#eeedf7')
    root.configure(bg=BG)
    shell = tk.Frame(root, bg=BG)
    shell.pack(fill='both', expand=True)
    sidebar = tk.Frame(shell, bg=NAVY, width=190)
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    brand = tk.Frame(sidebar, bg=NAVY)
    brand.pack(fill='x', padx=22, pady=(30, 28))
    icon = tk.Canvas(brand, width=38, height=38, bg=NAVY, highlightthickness=0)
    icon.pack(anchor='w', pady=(0, 13))
    icon.create_oval(1, 1, 37, 37, fill='#8371f1', outline='')
    icon.create_polygon(15, 11, 15, 27, 27, 19, fill='white', outline='')
    label(brand, 'Bili Replay', size=17, color='white', bold=True).pack(anchor='w')
    label(brand, '直播回放下载器', size=9, color='#8f9ab5').pack(anchor='w', pady=(4, 0))
    active = tk.Frame(sidebar, bg='#303650')
    active.pack(fill='x', padx=14)
    tk.Frame(active, bg='#a798ff', width=3).pack(side='left', fill='y')
    label(active, '↓   下载回放', size=11, bold=True, color='white', padx=16, pady=13).pack(anchor='w')
    tip = tk.Frame(sidebar, bg='#252d46')
    tip.pack(side='bottom', fill='x', padx=18, pady=(12, 22))
    label(tip, '完整，才值得留存', size=9, color='#d5d9e8', bold=True).pack(anchor='w', padx=12, pady=(13, 5))
    label(tip, '不裁切 · 不重新编码\n以连续 MP4 保存', size=9, color='#929db8', justify='left').pack(anchor='w', padx=12, pady=(0, 13))
    utility = tk.Frame(sidebar, bg=NAVY)
    utility.pack(side='bottom', fill='x', padx=14, pady=(0, 0))
    from . import __version__
    label(utility, f'桌面客户端  v{__version__}', size=8, color='#727e9b').pack(anchor='w', padx=14, pady=(8, 2))
    ttk.Button(utility, text='使用帮助', style='Nav.TButton', command=w.help).pack(fill='x')
    w.network_button = ttk.Button(utility, text='网络设置', style='Nav.TButton', command=w.network_settings)
    w.network_button.pack(fill='x')
    ttk.Button(utility, text='关于与开源组件', style='Nav.TButton', command=w.about).pack(fill='x')
    workspace = tk.Frame(shell, bg=BG)
    workspace.pack(side='left', fill='both', expand=True)
    main_canvas = tk.Canvas(workspace, bg=BG, bd=0, highlightthickness=0)
    scroll_main = ttk.Scrollbar(workspace, orient='vertical', command=main_canvas.yview)
    main_canvas.configure(yscrollcommand=scroll_main.set)
    main_canvas.pack(side='left', fill='both', expand=True)
    main = tk.Frame(main_canvas, bg=BG)
    main_id = main_canvas.create_window(30, 26, anchor='nw', window=main)
    w.main_content = main
    w.scroll_canvas = main_canvas
    def fit_content(event=None):
        main_canvas.itemconfigure(main_id, width=max(650, main_canvas.winfo_width() - 60))
        height = main.winfo_reqheight() + 52
        main_canvas.configure(scrollregion=(0, 0, main_canvas.winfo_width(), height))
        if height > main_canvas.winfo_height() + 2:
            if not scroll_main.winfo_manager():
                scroll_main.pack(side='right', fill='y')
        elif scroll_main.winfo_manager():
            scroll_main.pack_forget()
            main_canvas.yview_moveto(0)
    main_canvas.bind('<Configure>', fit_content)
    main.bind('<Configure>', fit_content)
    def wheel(event):
        if str(event.widget).startswith(str(main_canvas)) and event.widget not in (w.link, w.details):
            main_canvas.yview_scroll(-int(event.delta / 120), 'units')
    root.bind_all('<MouseWheel>', wheel, add='+')
    top = tk.Frame(main, bg=BG)
    top.pack(fill='x', pady=(0, 22))
    label(top, '下载直播回放', size=23, bold=True).pack(anchor='w')
    label(top, '把喜欢的直播，完整留在你的电脑里。', size=10, color=MUTED).pack(anchor='w', pady=(7, 0))
    body = tk.Frame(main, bg=BG)
    body.pack(fill='x')
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, minsize=274)
    form = Card(body)
    form.grid(row=0, column=0, sticky='nsew', padx=(0, 18))
    left = form.body
    section(left, '01', '回放链接', '从直播回放的“投片段”页面，复制完整网址。')
    editor = tk.Frame(left, bg='#f8f9fc', highlightbackground=BORDER,
                      highlightcolor='#a99ded', highlightthickness=1)
    editor.pack(fill='x')
    w.link = tk.Text(editor, height=3, wrap='char', width=35, bg='#f8f9fc', fg=INK,
                     insertbackground=ACCENT, relief='flat', bd=0, padx=12, pady=12,
                     highlightthickness=0, font=(FONT, 10), selectbackground='#ded8ff')
    w.link.pack(fill='x')
    placeholder = tk.Label(editor, text='粘贴直播回放页面的完整链接…', bg='#f8f9fc',
                           fg='#a1a8bb', font=(FONT, 10), bd=0)
    placeholder.place(x=12, y=12)
    placeholder.bind('<Button-1>', lambda event: w.link.focus_set())
    def update_placeholder(event=None):
        if not w.link.edit_modified():
            return
        if w.link.get('1.0', 'end').strip():
            placeholder.place_forget()
        else:
            placeholder.place(x=12, y=12)
        w.link.edit_modified(False)
    w.link.bind('<<Modified>>', update_placeholder)
    tools = tk.Frame(left, bg='white')
    tools.pack(fill='x', pady=(8, 22))
    w.paste_button = ttk.Button(tools, text='从剪贴板粘贴', style='Link.TButton', command=w.paste_link)
    w.paste_button.pack(side='left')
    ttk.Button(tools, text='去直播中心 ↗', style='Link.TButton',
               command=lambda: webbrowser.open('https://link.bilibili.com/#/my-room/live-record')).pack(side='right')
    section(left, '02', '保存位置', '为每场直播创建独立文件夹，方便查找。')
    path_row = tk.Frame(left, bg='white')
    path_row.pack(fill='x')
    path_row.columnconfigure(0, weight=1)
    w.folder = tk.StringVar(value=str(Path.home() / 'Videos' / 'B站直播回放'))
    w.folder_entry = ttk.Entry(path_row, textvariable=w.folder, width=24)
    w.folder_entry.grid(row=0, column=0, sticky='ew')
    w.choose_button = ttk.Button(path_row, text='浏览…', style='Soft.TButton', command=w.choose_folder)
    w.choose_button.grid(row=0, column=1, padx=(8, 0))
    info = tk.Frame(left, bg='#f1f8f6')
    info.pack(fill='x', pady=(22, 0))
    label(info, '✓  原样保存为 MP4', size=10, color='#3d8272', bold=True).pack(anchor='w', padx=14, pady=(12, 4))
    label(info, '保留完整内容，完成后自动检查视频完整性。', size=9, color='#6d938a').pack(anchor='w', padx=14, pady=(0, 12))
    auth = Card(body, padding=22)
    auth.grid(row=0, column=1, sticky='nsew')
    right = auth.body
    auth_title = tk.Frame(right, bg='white')
    auth_title.pack(fill='x')
    label(auth_title, '扫码登录', size=12, bold=True).pack(side='left')
    w.auth_badge = label(auth_title, '未登录', size=8, color='#8c94a4', padx=8, pady=3)
    w.auth_badge.configure(bg='#f0f2f6')
    w.auth_badge.pack(side='right')
    label(right, '使用手机 B 站 App 扫一扫', size=9, color=MUTED).pack(anchor='w', pady=(9, 15))
    qr_box = tk.Frame(right, bg='#f8f9fc', width=222, height=222,
                      highlightbackground=BORDER, highlightthickness=1)
    qr_box.pack(anchor='center')
    qr_box.pack_propagate(False)
    w.qr_label = tk.Label(qr_box, bg='#f8f9fc', fg='#8f97b2', bd=0, compound='center',
                          text='扫码后，即刻开始\n\n点击下方按钮获取二维码', font=(FONT, 10))
    w.qr_label.pack(fill='both', expand=True, padx=6, pady=6)
    w.account = tk.StringVar(value='登录仅在本次运行中有效')
    label(right, size=9, color=MUTED, textvariable=w.account).pack(pady=(12, 10))
    w.login_button = ttk.Button(right, text='获取登录二维码', style='Soft.TButton', command=lambda: w.begin('login'))
    w.login_button.pack(fill='x')
    label(right, '通过 B 站官方接口登录', size=8, color='#a0a7b7').pack(pady=(12, 0))
    task = Card(main, padding=22)
    task.pack(fill='x', pady=(18, 0))
    panel = task.body
    row = tk.Frame(panel, bg='white')
    row.pack(fill='x')
    w.task_title = label(row, '准备下载', size=12, bold=True)
    w.task_title.pack(side='left')
    w.percent = tk.StringVar(value='等待开始')
    w.percent_label = label(row, size=11, color=ACCENT, bold=True, textvariable=w.percent)
    w.percent_label.pack(side='right')
    w.status = tk.StringVar(value='填好回放链接，选择保存位置，就可以开始了。')
    w.status_label = label(panel, size=9, color=MUTED, textvariable=w.status,
                           wraplength=650, anchor='w', justify='left')
    w.status_label.pack(fill='x', pady=(10, 14))
    track = tk.Frame(panel, bg='#eeedf7', height=7)
    track.pack(fill='x')
    track.pack_propagate(False)
    w.progress = ttk.Progressbar(track, maximum=100, length=100)
    w.progress.pack(fill='both', expand=True)
    actions = tk.Frame(panel, bg='white')
    actions.pack(fill='x', pady=(18, 0))
    w.download_button = ttk.Button(actions, text='开始下载完整回放  ↓', style='Primary.TButton', command=lambda: w.begin('download'))
    w.download_button.pack(side='left')
    w.cancel_button = ttk.Button(actions, text='停止', state='disabled', command=w.cancel)
    w.cancel_button.pack(side='left', padx=10)
    w.open_button = ttk.Button(actions, text='打开保存文件夹', command=w.open_folder)
    w.open_button.pack(side='right')
    foot = tk.Frame(main, bg=BG)
    foot.pack(fill='x', pady=(14, 0))
    w.details_button = tk.Button(foot, text='查看任务详情  ▾', command=w.toggle_details, bd=0,
                                 relief='flat', bg=BG, fg=MUTED, activebackground=BG,
                                 activeforeground=ACCENT, cursor='hand2', font=(FONT, 9))
    w.details_button.pack(side='left')
    label(foot, '只保存本人或已获授权的回放', size=8, color='#a0a7b7').pack(side='right')
    w.details_panel = tk.Frame(main, bg='#eef0f6')
    w.details = tk.Text(w.details_panel, height=4, wrap='word', bg='#eef0f6', fg='#738097',
                        font=(FONT, 9), state='disabled', bd=0, padx=12, pady=10)
    scroll = ttk.Scrollbar(w.details_panel, command=w.details.yview)
    w.details.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    w.details.pack(fill='both', expand=True)
    w.details_visible = False
    w.proxy = ''
    w.link.bind('<FocusIn>', lambda event: editor.configure(highlightbackground='#a99ded'))
    w.link.bind('<FocusOut>', lambda event: editor.configure(highlightbackground=BORDER))
    root.bind('<Control-Return>', lambda event: w.begin('download'))
    def resize(event):
        w.status_label.configure(wraplength=max(320, event.width - 45))
    panel.bind('<Configure>', resize)
