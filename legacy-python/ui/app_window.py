"""
VRC-VideoTools - 主界面 GUI 模块
基于 Python Tkinter + TTK + Pillow 构建现代化深色风格桌面应用
支持全平台智能解析、视频封面加载、多分辨率切换、Cloudflare 全房间公网同步穿透、VRChat防盗链中继及浏览器实时预览
"""

from __future__ import annotations
import io
import os
import sys
import threading
import webbrowser
from typing import Optional, List, Dict
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from PIL import Image, ImageTk

from parsers import UnifiedParser, VideoInfo, VideoQuality, detect_platform
from server.proxy_server import VRCProxyServer
from server.tunnel_manager import CloudflareTunnel
from utils.logger import get_logger

logger = get_logger("gui")


# 深色现代主题配色方案 (Catppuccin Mocha Inspired)
THEME = {
    "bg": "#181825",            # 全局最底层背景
    "card_bg": "#1e1e2e",       # 卡片底色
    "card_border": "#313244",   # 边框
    "input_bg": "#11111b",      # 输入框背景
    "text": "#cdd6f4",          # 主文本色
    "text_muted": "#a6adc8",    # 辅助文本色
    "accent": "#89b4fa",        # 重点主色 (蓝)
    "accent_hover": "#b4befe",  # 主色悬浮
    "green": "#a6e3a1",         # 成功/就绪 (绿)
    "green_hover": "#94e2d5",
    "red": "#f38ba8",           # 警示 (红)
    "orange": "#fab387",        # 警告/快手 (橙)
    "purple": "#cba6f7",        # 次重点 (紫)
    "douyin": "#20c997",        # 抖音标志色
    "bilibili": "#00a1d6",      # B站标志色
    "kuaishou": "#ff5000",      # 快手标志色
}


class VRCVideoToolsApp:
    """VRC-VideoTools GUI 应用程序"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VRC-VideoTools - 视频解析 & VRChat全房间流媒体中继工具")
        self.root.geometry("1020x800")
        self.root.minsize(920, 720)
        self.root.configure(bg=THEME["bg"])

        # 初始化解析引擎与本地流代理服务
        self.parser = UnifiedParser()
        self.proxy_server = VRCProxyServer(port=9527)
        self.proxy_server.start()

        # Cloudflare 快速公网隧道 (用于解决 B 站跨互联网全房间同步)
        self.tunnel = CloudflareTunnel(local_port=9527)
        self.tunnel_url: Optional[str] = None
        self.tunnel_state = "stopped"  # "stopped" | "starting" | "running"

        # 运行状态
        self.current_info: Optional[VideoInfo] = None
        self.cover_image_ref: Optional[ImageTk.PhotoImage] = None
        self.history: List[VideoInfo] = []

        # 界面布局搭建
        self._setup_styles()
        self._build_ui()

        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        """配置 TTK 控件样式"""
        style = ttk.Style(self.root)
        style.theme_use("clam")

        # 基础 Frame
        style.configure("TFrame", background=THEME["bg"])
        style.configure("Card.TFrame", background=THEME["card_bg"])

        # 标签
        style.configure("TLabel", background=THEME["bg"], foreground=THEME["text"], font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=THEME["card_bg"], foreground=THEME["text"], font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=THEME["card_bg"], foreground=THEME["text_muted"], font=("Segoe UI", 9))

        # 单选按钮
        style.configure("TRadiobutton", background=THEME["card_bg"], foreground=THEME["text"], font=("Segoe UI", 9))
        style.map("TRadiobutton", background=[("active", THEME["card_bg"])])

        # 下拉框
        style.configure("TCombobox", fieldbackground=THEME["input_bg"], background=THEME["card_bg"], foreground=THEME["text"])

    def _build_ui(self):
        """构建界面主元素"""
        main_container = tk.Frame(self.root, bg=THEME["bg"], padx=20, pady=16)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 1. 顶部 Header 栏 (标题 + 代理服务状态卡片)
        self._build_header(main_container)

        # 2. 链接输入与操作区
        self._build_input_section(main_container)

        # 3. 视频信息与解析结果卡片 (含全房间同步公网穿透控制)
        self._build_result_section(main_container)

        # 4. 底部状态与历史记录栏
        self._build_bottom_section(main_container)

    def _build_header(self, parent: tk.Widget):
        """顶部信息栏"""
        header_frame = tk.Frame(parent, bg=THEME["bg"])
        header_frame.pack(fill=tk.X, pady=(0, 14))

        # 左侧标题
        title_box = tk.Frame(header_frame, bg=THEME["bg"])
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        title_lbl = tk.Label(
            title_box,
            text="🎬 VRC-VideoTools",
            font=("Segoe UI", 16, "bold"),
            fg=THEME["accent"],
            bg=THEME["bg"]
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            title_box,
            text="哔哩哔哩 · 抖音 · 快手 | 视频解析 & VRChat全房间跨网同步流媒体中继",
            font=("Segoe UI", 9),
            fg=THEME["text_muted"],
            bg=THEME["bg"]
        )
        sub_lbl.pack(anchor="w")

        # 右侧代理状态卡片
        status_card = tk.Frame(
            header_frame,
            bg=THEME["card_bg"],
            highlightbackground=THEME["card_border"],
            highlightthickness=1,
            padx=12,
            pady=6
        )
        status_card.pack(side=tk.RIGHT)

        status_top = tk.Frame(status_card, bg=THEME["card_bg"])
        status_top.pack(fill=tk.X)

        self.server_dot = tk.Label(status_top, text="●", fg=THEME["green"], bg=THEME["card_bg"], font=("Segoe UI", 10))
        self.server_dot.pack(side=tk.LEFT, padx=(0, 4))

        self.server_status_text = tk.Label(
            status_top,
            text="本地流媒体中继运行中",
            font=("Segoe UI", 9, "bold"),
            fg=THEME["text"],
            bg=THEME["card_bg"]
        )
        self.server_status_text.pack(side=tk.LEFT)

        local_ip = self.proxy_server.get_local_ip()
        ip_info = f"本地端口: {self.proxy_server.port} | 局域网: {local_ip}"
        self.server_ip_lbl = tk.Label(
            status_card,
            text=ip_info,
            font=("Consolas", 8),
            fg=THEME["text_muted"],
            bg=THEME["card_bg"]
        )
        self.server_ip_lbl.pack(anchor="w", pady=(2, 0))

    def _build_input_section(self, parent: tk.Widget):
        """输入与控制区域"""
        card = tk.Frame(
            parent,
            bg=THEME["card_bg"],
            highlightbackground=THEME["card_border"],
            highlightthickness=1,
            padx=16,
            pady=12
        )
        card.pack(fill=tk.X, pady=(0, 12))

        # 平台选择单选栏
        nav_frame = tk.Frame(card, bg=THEME["card_bg"])
        nav_frame.pack(fill=tk.X, pady=(0, 8))

        tk.Label(nav_frame, text="识别模式:", font=("Segoe UI", 9, "bold"), fg=THEME["text"], bg=THEME["card_bg"]).pack(side=tk.LEFT, padx=(0, 10))

        self.platform_var = tk.StringVar(value="auto")
        platforms = [
            ("🤖 全平台智能识别", "auto"),
            ("📺 哔哩哔哩 (BV/b23)", "bilibili"),
            ("🎵 抖音短视频", "douyin"),
            ("⚡ 快手短视频", "kuaishou"),
        ]
        for text, val in platforms:
            rb = tk.Radiobutton(
                nav_frame,
                text=text,
                value=val,
                variable=self.platform_var,
                bg=THEME["card_bg"],
                fg=THEME["text"],
                activebackground=THEME["card_bg"],
                activeforeground=THEME["accent"],
                selectcolor=THEME["input_bg"],
                font=("Segoe UI", 9),
                cursor="hand2"
            )
            rb.pack(side=tk.LEFT, padx=6)

        # 聚合输入栏容器
        input_container = tk.Frame(card, bg=THEME["card_bg"])
        input_container.pack(fill=tk.X)

        self.input_entry = tk.Entry(
            input_container,
            bg=THEME["input_bg"],
            fg=THEME["text"],
            insertbackground=THEME["accent"],
            font=("Segoe UI", 10),
            relief=tk.FLAT,
            highlightbackground=THEME["card_border"],
            highlightcolor=THEME["accent"],
            highlightthickness=1
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self.on_parse_click())
        self.input_entry.bind("<Control-v>", self._on_entry_paste_override)
        self.input_entry.bind("<Control-V>", self._on_entry_paste_override)
        self.input_entry.bind("<FocusIn>", lambda e: self.input_entry.select_range(0, tk.END))

        # 1. 粘贴并解析按钮 (一键读取剪切板并立刻解析)
        self.paste_and_parse_btn = tk.Button(
            input_container,
            text="📋 粘贴并解析",
            command=self.on_paste_and_parse_click,
            bg=THEME["accent"],
            fg="#0f111a",
            activebackground=THEME["accent_hover"],
            activeforeground="#000000",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
            cursor="hand2"
        )
        self.paste_and_parse_btn.pack(side=tk.LEFT, padx=(0, 6))

        # 2. 复制直链按钮 (一键将解析出的直链复制到剪贴板)
        self.copy_direct_top_btn = tk.Button(
            input_container,
            text="🔗 复制直链",
            command=self.on_copy_direct_top_click,
            bg=THEME["green"],
            fg="#0f111a",
            activebackground=THEME["green_hover"],
            activeforeground="#000000",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=7,
            cursor="hand2"
        )
        self.copy_direct_top_btn.pack(side=tk.LEFT, padx=(0, 6))

        # 3. 辅助解析按钮
        self.parse_btn = tk.Button(
            input_container,
            text="🚀 解析",
            command=self.on_parse_click,
            bg=THEME["card_border"],
            fg=THEME["text"],
            activebackground=THEME["accent"],
            activeforeground="#000000",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=12,
            pady=7,
            cursor="hand2"
        )
        self.parse_btn.pack(side=tk.LEFT, padx=(0, 6))

        # 4. 清空按钮
        clear_btn = tk.Button(
            input_container,
            text="清空",
            command=self.on_clear_click,
            bg=THEME["card_border"],
            fg=THEME["text_muted"],
            activebackground=THEME["red"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=10,
            pady=7,
            cursor="hand2"
        )
        clear_btn.pack(side=tk.LEFT)

        # 选项与提示条
        opt_frame = tk.Frame(card, bg=THEME["card_bg"])
        opt_frame.pack(fill=tk.X, pady=(6, 0))

        self.auto_copy_var = tk.BooleanVar(value=True)
        auto_copy_cb = tk.Checkbutton(
            opt_frame,
            text="解析成功后自动复制直链到剪贴板 (极速进VRC粘贴)",
            variable=self.auto_copy_var,
            bg=THEME["card_bg"],
            fg=THEME["green"],
            activebackground=THEME["card_bg"],
            activeforeground=THEME["green"],
            selectcolor=THEME["input_bg"],
            font=("Segoe UI", 8),
            cursor="hand2"
        )
        auto_copy_cb.pack(side=tk.RIGHT)

        self.status_lbl = tk.Label(
            opt_frame,
            text="点击【粘贴并解析】自动读取剪贴板并解析，解析后点击【复制直链】或自动写入剪切板，直接在 VRChat 中播放！",
            font=("Segoe UI", 9),
            fg=THEME["text_muted"],
            bg=THEME["card_bg"],
            anchor="w"
        )
        self.status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _build_result_section(self, parent: tk.Widget):
        """解析结果与播放链接展示卡片"""
        self.result_card = tk.Frame(
            parent,
            bg=THEME["card_bg"],
            highlightbackground=THEME["card_border"],
            highlightthickness=1,
            padx=18,
            pady=14
        )
        self.result_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 顶部视频概览行 (封面 + 元数据)
        meta_row = tk.Frame(self.result_card, bg=THEME["card_bg"])
        meta_row.pack(fill=tk.X, pady=(0, 12))

        # 封面图
        self.cover_frame = tk.Frame(
            meta_row,
            bg="#000000",
            width=200,
            height=112,
            highlightbackground=THEME["card_border"],
            highlightthickness=1
        )
        self.cover_frame.pack_propagate(False)
        self.cover_frame.pack(side=tk.LEFT, padx=(0, 14))

        self.cover_label = tk.Label(self.cover_frame, bg="#000000", text="暂无封面", fg=THEME["text_muted"])
        self.cover_label.pack(fill=tk.BOTH, expand=True)

        # 右侧视频详情
        meta_info = tk.Frame(meta_row, bg=THEME["card_bg"])
        meta_info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tag_row = tk.Frame(meta_info, bg=THEME["card_bg"])
        tag_row.pack(fill=tk.X, pady=(0, 4))

        self.platform_badge = tk.Label(
            tag_row,
            text="等待解析",
            font=("Segoe UI", 8, "bold"),
            bg=THEME["card_border"],
            fg=THEME["text"],
            padx=8,
            pady=2
        )
        self.platform_badge.pack(side=tk.LEFT, padx=(0, 8))

        self.duration_badge = tk.Label(
            tag_row,
            text="⏱ 00:00",
            font=("Segoe UI", 8),
            bg=THEME["input_bg"],
            fg=THEME["text_muted"],
            padx=8,
            pady=2
        )
        self.duration_badge.pack(side=tk.LEFT, padx=(0, 8))

        self.size_badge = tk.Label(
            tag_row,
            text="💾 - MB",
            font=("Segoe UI", 8),
            bg=THEME["input_bg"],
            fg=THEME["text_muted"],
            padx=8,
            pady=2
        )
        self.size_badge.pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(tag_row, text="画质:", font=("Segoe UI", 9), fg=THEME["text_muted"], bg=THEME["card_bg"]).pack(side=tk.LEFT, padx=(8, 4))
        self.quality_combo = ttk.Combobox(tag_row, state="readonly", width=14, font=("Segoe UI", 8))
        self.quality_combo.pack(side=tk.LEFT)
        self.quality_combo.bind("<<ComboboxSelected>>", self._on_quality_changed)

        self.title_label = tk.Label(
            meta_info,
            text="暂无解析结果，请在上方输入框粘贴视频链接后点击【立即解析】",
            font=("Segoe UI", 11, "bold"),
            fg=THEME["text"],
            bg=THEME["card_bg"],
            anchor="w",
            justify=tk.LEFT,
            wraplength=640
        )
        self.title_label.pack(fill=tk.X, pady=(3, 3))

        self.author_label = tk.Label(
            meta_info,
            text="创作者: -",
            font=("Segoe UI", 9),
            fg=THEME["text_muted"],
            bg=THEME["card_bg"],
            anchor="w"
        )
        self.author_label.pack(fill=tk.X)

        # 分割线
        sep = tk.Frame(self.result_card, bg=THEME["card_border"], height=1)
        sep.pack(fill=tk.X, pady=(0, 10))

        # ----------------- 播放范围与全房间同步设置栏 -----------------
        scope_box = tk.Frame(self.result_card, bg=THEME["card_bg"])
        scope_box.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            scope_box,
            text="👥 播放同步范围 (如何让别人也能看见):",
            font=("Segoe UI", 9, "bold"),
            fg=THEME["accent"],
            bg=THEME["card_bg"]
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.sync_mode_var = tk.StringVar(value="tunnel")
        sync_modes = [
            ("🌐 公网穿透 (全房间跨网同步·推荐)", "tunnel"),
            ("☁️ 自定义公网/VPS", "custom"),
            ("🏠 局域网/同WiFi", "lan"),
            ("💻 仅本机自己", "local")
        ]
        for label, val in sync_modes:
            rb = tk.Radiobutton(
                scope_box,
                text=label,
                value=val,
                variable=self.sync_mode_var,
                command=self._on_sync_mode_changed,
                bg=THEME["card_bg"],
                fg=THEME["text"],
                selectcolor=THEME["input_bg"],
                font=("Segoe UI", 8),
                cursor="hand2"
            )
            rb.pack(side=tk.LEFT, padx=5)

        # 公网隧道控制条 (动态展现)
        self.tunnel_bar = tk.Frame(self.result_card, bg=THEME["input_bg"], padx=10, pady=6)
        self.tunnel_bar.pack(fill=tk.X, pady=(0, 10))

        self.tunnel_btn = tk.Button(
            self.tunnel_bar,
            text="⚡ 启动公网穿透",
            command=self.on_toggle_tunnel_click,
            bg=THEME["accent"],
            fg="#0f111a",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=3,
            cursor="hand2"
        )
        self.tunnel_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.tunnel_status_lbl = tk.Label(
            self.tunnel_bar,
            text="未开启公网穿透。点击【启动公网穿透】可一键生成免费公网 HTTPS 域名，让房间内任何人都能同步观看 B 站视频！",
            font=("Segoe UI", 8),
            fg=THEME["text_muted"],
            bg=THEME["input_bg"]
        )
        self.tunnel_status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 自定义公网 Host 条 (默认隐藏)
        self.custom_host_bar = tk.Frame(self.result_card, bg=THEME["input_bg"], padx=10, pady=6)
        tk.Label(
            self.custom_host_bar,
            text="自定义服务器/公网IP (如 http://vps.com:9527):",
            font=("Segoe UI", 8),
            fg=THEME["text"],
            bg=THEME["input_bg"]
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.custom_host_entry = tk.Entry(
            self.custom_host_bar,
            bg=THEME["card_bg"],
            fg=THEME["accent"],
            font=("Consolas", 8),
            relief=tk.FLAT
        )
        self.custom_host_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.custom_host_entry.bind("<KeyRelease>", lambda e: self._refresh_output_urls())

        # ----------------- 链接输出区域 -----------------
        # 1. 官方全房间同步直链 (免代理 · 免穿透 · VRChat所有人跨网直接同步播放)
        direct_box = tk.Frame(self.result_card, bg=THEME["card_bg"])
        direct_box.pack(fill=tk.X, pady=(0, 10))

        direct_header = tk.Frame(direct_box, bg=THEME["card_bg"])
        direct_header.pack(fill=tk.X, pady=(0, 3))

        tk.Label(
            direct_header,
            text="🟢 官方全房间同步直链 (首选推荐 · 免代理 · 免穿透 · 所有人可直接同步观看):",
            font=("Segoe UI", 9, "bold"),
            fg=THEME["green"],
            bg=THEME["card_bg"]
        ).pack(side=tk.LEFT)

        self.direct_tip_lbl = tk.Label(
            direct_header,
            text="（已逆向生成免防盗链授权令牌，VRChat房间内所有好友均可直接同步播放）",
            font=("Segoe UI", 8),
            fg=THEME["green"],
            bg=THEME["card_bg"]
        )
        self.direct_tip_lbl.pack(side=tk.LEFT, padx=(4, 0))

        direct_input_frame = tk.Frame(direct_box, bg=THEME["card_bg"])
        direct_input_frame.pack(fill=tk.X)

        self.direct_url_entry = tk.Entry(
            direct_input_frame,
            bg=THEME["input_bg"],
            fg=THEME["green"],
            font=("Consolas", 9),
            relief=tk.FLAT,
            highlightbackground=THEME["card_border"],
            highlightthickness=1
        )
        self.direct_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))

        self.copy_direct_btn = tk.Button(
            direct_input_frame,
            text="📋 复制全员直链",
            command=self.on_copy_direct_click,
            bg=THEME["green"],
            fg="#0f111a",
            activebackground=THEME["green_hover"],
            activeforeground="#000000",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=5,
            cursor="hand2"
        )
        self.copy_direct_btn.pack(side=tk.LEFT)

        # 2. 中继/穿透代理备用链接
        vrc_box = tk.Frame(self.result_card, bg=THEME["card_bg"])
        vrc_box.pack(fill=tk.X, pady=(0, 8))

        vrc_header = tk.Frame(vrc_box, bg=THEME["card_bg"])
        vrc_header.pack(fill=tk.X, pady=(0, 3))

        self.vrc_title_lbl = tk.Label(
            vrc_header,
            text="⚪ 本地/公网中继备用链接 (可选 · 适用于自定义服务器、局域网或内网穿透):",
            font=("Segoe UI", 9),
            fg=THEME["text_muted"],
            bg=THEME["card_bg"]
        )
        self.vrc_title_lbl.pack(side=tk.LEFT)

        vrc_input_frame = tk.Frame(vrc_box, bg=THEME["card_bg"])
        vrc_input_frame.pack(fill=tk.X)

        self.vrc_url_entry = tk.Entry(
            vrc_input_frame,
            bg=THEME["input_bg"],
            fg=THEME["text"],
            font=("Consolas", 9),
            relief=tk.FLAT,
            highlightbackground=THEME["card_border"],
            highlightthickness=1
        )
        self.vrc_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))

        self.copy_vrc_btn = tk.Button(
            vrc_input_frame,
            text="复制中继链接",
            command=self.on_copy_vrc_click,
            bg=THEME["card_border"],
            fg=THEME["text"],
            activebackground=THEME["accent"],
            activeforeground="#000000",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=14,
            pady=5,
            cursor="hand2"
        )
        self.copy_vrc_btn.pack(side=tk.LEFT)

        # 快捷辅助按钮行
        action_row = tk.Frame(self.result_card, bg=THEME["card_bg"])
        action_row.pack(fill=tk.X, pady=(2, 0))

        preview_btn = tk.Button(
            action_row,
            text="🌐 在浏览器中实时测试播放",
            command=self.on_browser_preview_click,
            bg=THEME["card_border"],
            fg=THEME["accent"],
            activebackground=THEME["accent"],
            activeforeground="#000000",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=14,
            pady=4,
            cursor="hand2"
        )
        preview_btn.pack(side=tk.LEFT, padx=(0, 10))

        copy_title_btn = tk.Button(
            action_row,
            text="📄 复制标题",
            command=self.on_copy_title_click,
            bg=THEME["card_border"],
            fg=THEME["text"],
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=12,
            pady=4,
            cursor="hand2"
        )
        copy_title_btn.pack(side=tk.LEFT)

    def _build_bottom_section(self, parent: tk.Widget):
        """底部历史记录栏"""
        history_box = tk.Frame(parent, bg=THEME["bg"])
        history_box.pack(fill=tk.X)

        tk.Label(
            history_box,
            text="最近解析历史 (双击快速载入):",
            font=("Segoe UI", 8, "bold"),
            fg=THEME["text_muted"],
            bg=THEME["bg"]
        ).pack(anchor="w", pady=(0, 4))

        self.history_listbox = tk.Listbox(
            history_box,
            bg=THEME["card_bg"],
            fg=THEME["text"],
            selectbackground=THEME["card_border"],
            selectforeground=THEME["accent"],
            font=("Segoe UI", 9),
            height=3,
            relief=tk.FLAT,
            highlightbackground=THEME["card_border"],
            highlightthickness=1
        )
        self.history_listbox.pack(fill=tk.X)
        self.history_listbox.bind("<Double-Button-1>", self._on_history_double_click)

    # ----------------- 事件与逻辑处理 -----------------

    def _on_sync_mode_changed(self):
        """同步范围切换时显示/隐藏对应控制条"""
        mode = self.sync_mode_var.get()
        if mode == "tunnel":
            self.tunnel_bar.pack(fill=tk.X, pady=(0, 10), after=self.tunnel_bar.master.children["!frame4"])
            self.custom_host_bar.pack_forget()
        elif mode == "custom":
            self.custom_host_bar.pack(fill=tk.X, pady=(0, 10), after=self.custom_host_bar.master.children["!frame4"])
            self.tunnel_bar.pack_forget()
        else:
            self.tunnel_bar.pack_forget()
            self.custom_host_bar.pack_forget()

        self._refresh_output_urls()

    def on_toggle_tunnel_click(self):
        """开关 Cloudflare 公网隧道"""
        if self.tunnel_state == "stopped":
            self.tunnel_state = "starting"
            self.tunnel_btn.config(text="⏳ 正在建立隧道...", state=tk.DISABLED)
            self.tunnel_status_lbl.config(
                text="正在连接 Cloudflare 边缘节点生成免费 HTTPS 公网隧道，请稍候...",
                fg=THEME["accent"]
            )
            self.tunnel.start(
                on_ready=lambda url: self.root.after(0, self._on_tunnel_ready, url),
                on_error=lambda err: self.root.after(0, self._on_tunnel_error, err)
            )
        else:
            self.tunnel.stop()
            self.tunnel_state = "stopped"
            self.tunnel_url = None
            self.tunnel_btn.config(text="⚡ 启动公网穿透", state=tk.NORMAL, bg=THEME["accent"])
            self.tunnel_status_lbl.config(
                text="未开启公网穿透。点击【启动公网穿透】可一键生成免费公网域名，让房间内任何人都能同步观看 B 站！",
                fg=THEME["text_muted"]
            )
            self._refresh_output_urls()

    def _on_tunnel_ready(self, url: str):
        """公网隧道就绪回调"""
        self.tunnel_url = url
        self.tunnel_state = "running"
        self.tunnel_btn.config(text="🛑 停止公网穿透", state=tk.NORMAL, bg=THEME["red"])
        self.tunnel_status_lbl.config(
            text=f"✅ 公网隧道运行中！全球访问节点: {url} (房间内的所有人均可同步流畅观看！)",
            fg=THEME["green"]
        )
        self.set_status("✅ Cloudflare 全球公网隧道已就绪，已自动更新 VRChat 播放链接！")
        self._refresh_output_urls()

    def _on_tunnel_error(self, err_msg: str):
        """公网隧道出错回调"""
        self.tunnel_state = "stopped"
        self.tunnel_url = None
        self.tunnel_btn.config(text="⚡ 启动公网穿透", state=tk.NORMAL, bg=THEME["accent"])
        self.tunnel_status_lbl.config(text=f"❌ 隧道连接异常: {err_msg}", fg=THEME["red"])

    def _on_entry_paste_override(self, event=None):
        """用户在输入框按 Ctrl+V 快捷键时，彻底覆盖清空原有内容并粘贴新链接"""
        try:
            text = self.root.clipboard_get()
            if text:
                self.input_entry.delete(0, tk.END)
                self.input_entry.insert(0, text.strip())
                self.input_entry.icursor(tk.END)
                return "break"  # 阻止 Tkinter 原生追加行为
        except Exception:
            pass
        return None

    def _reset_result_display(self, status_hint: str = ""):
        """彻底重置并覆盖上一次视频解析卡片的所有残留数据"""
        self.current_info = None
        self.title_label.config(text="正在解析新视频，请稍候...")
        self.author_label.config(text="创作者 / UP主: 获取中...")
        self.platform_badge.config(text="[解析中]", bg=THEME["card_border"], fg=THEME["text"])
        self.duration_badge.config(text="⏱ --:--")
        self.size_badge.config(text="💾 -- MB")
        self.quality_combo["values"] = []
        self.quality_combo.set("获取画质中...")
        self.direct_url_entry.delete(0, tk.END)
        self.vrc_url_entry.delete(0, tk.END)
        self.cover_label.config(image="", text="等待视频封面...")
        self.cover_image_ref = None
        if status_hint:
            self.set_status(status_hint)

    def on_paste_and_parse_click(self):
        """一键从剪切板读取，100% 覆盖清空旧输入与旧解析结果，立即触发极速解析"""
        try:
            text = self.root.clipboard_get()
            if not text or not text.strip():
                logger.warning("触发【粘贴并解析】，但系统剪贴板中为空或未读取到有效文本")
                self.set_status("剪贴板中未找到文本内容！", is_error=True)
                return
            clean_text = text.strip()
            logger.info(f"📋 触发【粘贴并解析】，读取剪贴板内容: {clean_text[:100]}...")
            # 1. 彻底清空输入框并覆盖写入新文本
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, clean_text)
            self.input_entry.icursor(tk.END)

            # 2. 彻底重置界面旧视频结果与旧直链，防止混淆
            self._reset_result_display(status_hint="📋 已覆盖旧内容并载入剪贴板，正在极速解析...")

            # 3. 立即触发解析流程
            self._start_parse(clean_text)
        except Exception as e:
            logger.error(f"读取剪贴板异常: {e}", exc_info=True)
            self.set_status("无法读取剪贴板，请检查剪切板权限", is_error=True)

    def on_copy_direct_top_click(self):
        """一键将解析出的视频直链复制到剪切板"""
        if not self.current_info or not self.current_info.play_url:
            self.set_status("暂无解析出的直链，请先点击【粘贴并解析】！", is_error=True)
            return

        url = self.current_info.play_url
        logger.info(f"🔗 用户点击复制官方全员直链: {url[:100]}...")
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.root.update()

        orig_text = self.copy_direct_top_btn.cget("text")
        orig_bg = self.copy_direct_top_btn.cget("bg")
        self.copy_direct_top_btn.config(text="✅ 已复制直链!", bg=THEME["green_hover"])
        self.root.after(1500, lambda: self.copy_direct_top_btn.config(text=orig_text, bg=orig_bg))
        self.set_status("✅ 官方全员同步直链已复制到剪贴板！可直接在 VRChat 中粘贴播放！")

    def on_clear_click(self):
        """清空输入框与解析结果卡片"""
        logger.debug("清空输入框与解析结果")
        self.input_entry.delete(0, tk.END)
        self._reset_result_display()
        self.title_label.config(text="暂未解析视频")
        self.author_label.config(text="创作者 / UP主: --")
        self.platform_badge.config(text="[待解析]", bg=THEME["card_border"], fg=THEME["text"])
        self.set_status("已清空输入框与上一次解析结果")

    def on_parse_click(self):
        """点击解析按钮"""
        raw_text = self.input_entry.get().strip()
        if not raw_text:
            self.set_status("请先输入或粘贴视频链接！", is_error=True)
            return
        # 清空上一次结果，显示正在解析
        self._reset_result_display(status_hint="正在请求接口并解析直链，请稍候...")
        self._start_parse(raw_text)

    def _start_parse(self, raw_text: str):
        """统一启动解析线程"""
        self.paste_and_parse_btn.config(state=tk.DISABLED, text="⏳ 解析中...")
        self.parse_btn.config(state=tk.DISABLED, text="⏳ 解析中...")

        platform_hint = self.platform_var.get()
        logger.info(f"🚀 启动后台异步解析任务: 输入='{raw_text[:80]}...' | 模式={platform_hint}")
        threading.Thread(target=self._async_parse_worker, args=(raw_text, platform_hint), daemon=True).start()

    def _async_parse_worker(self, raw_text: str, platform_hint: str):
        """后台解析线程"""
        try:
            info = self.parser.parse(raw_text, platform_hint=platform_hint)
            self.root.after(0, self._render_parse_success, info)
        except Exception as e:
            logger.error(f"后台解析抛出异常: {e}", exc_info=True)
            self.root.after(0, self._render_parse_error, str(e))

    def _render_parse_success(self, info: VideoInfo):
        """主线程渲染解析成功的结果"""
        self.paste_and_parse_btn.config(state=tk.NORMAL, text="📋 粘贴并解析")
        self.parse_btn.config(state=tk.NORMAL, text="🚀 解析")
        self.current_info = info

        logger.info(f"🎉 渲染解析成功界面: [{info.platform_name}] 《{info.title}》 by {info.author} | 直链={info.play_url[:80]}...")

        # 1. 更新标题与作者
        self.title_label.config(text=info.title)
        self.author_label.config(text=f"创作者 / UP主: {info.author}")

        # 2. 更新徽章
        badge_colors = {
            "bilibili": (THEME["bilibili"], "#ffffff"),
            "douyin": (THEME["douyin"], "#000000"),
            "kuaishou": (THEME["kuaishou"], "#ffffff"),
        }
        bg_col, fg_col = badge_colors.get(info.platform, (THEME["card_border"], THEME["text"]))
        self.platform_badge.config(text=f"[{info.platform_name}]", bg=bg_col, fg=fg_col)
        self.duration_badge.config(text=f"⏱ {info.duration_str}")
        size_txt = f"💾 {info.size_mb} MB" if info.size_mb else "💾 动态流"
        self.size_badge.config(text=size_txt)

        # 3. 更新画质选项列表
        quality_labels = [q.label for q in info.qualities] if info.qualities else [info.quality]
        self.quality_combo["values"] = quality_labels
        if quality_labels:
            self.quality_combo.current(0)

        # 4. 根据平台展示不同的全房间同步提示
        if info.platform in ["douyin", "kuaishou"]:
            self.direct_tip_lbl.config(
                text=f"（🔥 {info.platform_name} 官方CDN无防盗链限制，直接复制下方直链即可让全房间所有人同步观看！）",
                fg=THEME["green"]
            )
        else:
            self.direct_tip_lbl.config(
                text="（🔥 已逆向注入免防盗链授权令牌，复制下方直链即可在 VRChat 中让全房间所有人直接同步播放！）",
                fg=THEME["green"]
            )

        # 5. 刷新 URL 字段
        self._refresh_output_urls()

        # 6. 自动复制直链到剪切板 (若开启选项)
        if self.auto_copy_var.get() and info.play_url:
            self.root.clipboard_clear()
            self.root.clipboard_append(info.play_url)
            self.root.update()
            orig_text = self.copy_direct_top_btn.cget("text")
            orig_bg = self.copy_direct_top_btn.cget("bg")
            self.copy_direct_top_btn.config(text="✅ 已自动复制直链!", bg=THEME["green_hover"])
            self.root.after(2000, lambda: self.copy_direct_top_btn.config(text=orig_text, bg=orig_bg))
            logger.info("已自动将免防盗链官方播放直链写入操作系统剪贴板")
            self.set_status(f"🎉 解析成功！已自动将【全房间同步直链】复制到剪贴板，直接在 VRChat 中按 Ctrl+V 即可播放！")
        else:
            self.set_status(f"🎉 解析成功！平台: {info.platform_name} | 时长: {info.duration_str}，点击【🔗 复制直链】即可播放！")

        # 7. 异步下载封面图
        if info.cover_url:
            threading.Thread(target=self._async_load_cover, args=(info.cover_url,), daemon=True).start()
        else:
            self.cover_label.config(text="无封面图片", image="")

        # 8. 加入历史记录列表
        self._add_to_history(info)

    def _render_parse_error(self, err_msg: str):
        """主线程渲染错误提示"""
        self.paste_and_parse_btn.config(state=tk.NORMAL, text="📋 粘贴并解析")
        self.parse_btn.config(state=tk.NORMAL, text="🚀 解析")
        logger.error(f"❌ 解析失败通知: {err_msg}")
        self.set_status(f"❌ 解析失败: {err_msg}", is_error=True)
        messagebox.showerror("解析失败", f"无法解析提供的视频内容：\n\n{err_msg}")

    def _async_load_cover(self, cover_url: str):
        """后台下载封面并渲染"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/"
        }
        try:
            resp = requests.get(cover_url, headers=headers, timeout=8)
            if resp.status_code == 200:
                raw_bytes = resp.content
                img = Image.open(io.BytesIO(raw_bytes))
                img = img.resize((200, 112), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.root.after(0, self._update_cover_image, photo)
        except Exception:
            pass

    def _update_cover_image(self, photo: ImageTk.PhotoImage):
        """主线程更新封面"""
        self.cover_image_ref = photo
        self.cover_label.config(image=photo, text="")

    def _on_quality_changed(self, event=None):
        """画质切换联动更新 URL"""
        if not self.current_info or not self.current_info.qualities:
            return
        idx = self.quality_combo.current()
        if 0 <= idx < len(self.current_info.qualities):
            selected_quality = self.current_info.qualities[idx]
            self.current_info.play_url = selected_quality.url
            self.current_info.quality = selected_quality.label
            self._refresh_output_urls()

    def _refresh_output_urls(self):
        """重新计算并填充 VRC 链接与直链输入框"""
        if not self.current_info:
            return

        target_url = self.current_info.play_url
        platform = self.current_info.platform
        mode = self.sync_mode_var.get()
        custom_host = self.custom_host_entry.get().strip()

        # 1. 计算 VRChat 代理流链接 (支持公网穿透/自定义域名/局域网/本机)
        vrc_url = self.proxy_server.get_stream_url(
            target_url,
            platform=platform,
            mode=mode,
            custom_host=custom_host,
            tunnel_url=self.tunnel_url or ""
        )
        self.vrc_url_entry.delete(0, tk.END)
        self.vrc_url_entry.insert(0, vrc_url)

        # 2. 填充原始直链
        self.direct_url_entry.delete(0, tk.END)
        self.direct_url_entry.insert(0, target_url)

    def on_copy_vrc_click(self):
        """复制 VRChat 播放链接到剪贴板"""
        url = self.vrc_url_entry.get().strip()
        if not url:
            self.set_status("暂无链接可复制，请先解析视频！", is_error=True)
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.root.update()

        orig_text = self.copy_vrc_btn.cget("text")
        orig_bg = self.copy_vrc_btn.cget("bg")
        self.copy_vrc_btn.config(text="✅ 已复制!", bg=THEME["green_hover"])
        self.root.after(1500, lambda: self.copy_vrc_btn.config(text=orig_text, bg=orig_bg))
        self.set_status("✅ VRChat 播放链接已复制！若使用的是公网穿透/局域网链接，房间内所有好友均可同步观看！")

    def on_copy_direct_click(self):
        """复制原始直链到剪贴板"""
        url = self.direct_url_entry.get().strip()
        if not url:
            self.set_status("暂无直链可复制！", is_error=True)
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.root.update()

        orig_text = self.copy_direct_btn.cget("text")
        self.copy_direct_btn.config(text="✅ 已复制!")
        self.root.after(1500, lambda: self.copy_direct_btn.config(text=orig_text))
        self.set_status("✅ 原始直链已复制！抖音和快手直链无需中继即可全员跨网同步！")

    def on_copy_title_click(self):
        """复制视频标题"""
        if self.current_info and self.current_info.title:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.current_info.title)
            self.set_status("✅ 视频标题已复制！")

    def on_browser_preview_click(self):
        """在系统浏览器中打开实时测试播放器"""
        if not self.current_info:
            self.set_status("请先解析视频后再进行预览测试！", is_error=True)
            return
        player_url = self.proxy_server.get_player_url(
            self.current_info.play_url,
            platform=self.current_info.platform
        )
        try:
            webbrowser.open(player_url)
            self.set_status("已在浏览器中启动流媒体测试播放器！")
        except Exception as e:
            self.set_status(f"打开浏览器失败: {e}", is_error=True)

    def _add_to_history(self, info: VideoInfo):
        """将解析成功的项加入历史记录"""
        self.history.insert(0, info)
        display_text = f"[{info.platform_name}] {info.title[:45]} ({info.duration_str})"
        self.history_listbox.insert(0, display_text)
        if len(self.history) > 15:
            self.history.pop()
            self.history_listbox.delete(15)

    def _on_history_double_click(self, event):
        """双击历史记录恢复显示"""
        selected_indices = self.history_listbox.curselection()
        if selected_indices:
            idx = selected_indices[0]
            if 0 <= idx < len(self.history):
                self._render_parse_success(self.history[idx])

    def set_status(self, message: str, is_error: bool = False):
        """设置状态栏文本"""
        color = THEME["red"] if is_error else THEME["text_muted"]
        self.status_lbl.config(text=message, fg=color)

    def _on_close(self):
        """关闭程序时停止代理与隧道服务"""
        try:
            self.tunnel.stop()
        except Exception:
            pass
        try:
            self.proxy_server.stop()
        except Exception:
            pass
        self.root.destroy()


def run_gui():
    """GUI 启动入口"""
    root = tk.Tk()
    app = VRCVideoToolsApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
