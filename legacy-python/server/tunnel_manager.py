"""
VRC-VideoTools - Cloudflare 快速公网隧道管理器
用于将本地 9527 代理端口一键映射为公网 HTTPS 域名 (trycloudflare.com)
使 VRChat 房间内的所有好友均可跨互联网同步播放 B 站等防盗链视频
"""

from __future__ import annotations
import os
import re
import sys
import time
import subprocess
import threading
from typing import Optional, Callable

from utils.logger import get_logger

logger = get_logger("tunnel")


class CloudflareTunnel:
    """Cloudflare Quick Tunnel 生命周期管理器"""

    def __init__(self, local_port: int = 9527):
        self.local_port = local_port
        self.process: Optional[subprocess.Popen] = None
        self.tunnel_url: Optional[str] = None
        self.is_running = False
        self._stop_event = threading.Event()
        self.on_url_ready: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def _get_cloudflared_path(self) -> str:
        """寻找 cloudflared 可执行文件路径"""
        # 1. 优先检查当前目录下的 cloudflared.exe
        curr_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_exe = os.path.join(curr_dir, "cloudflared.exe")
        if os.path.exists(local_exe):
            return local_exe
        return "cloudflared"

    def start(self, on_ready: Optional[Callable[[str], None]] = None, on_error: Optional[Callable[[str], None]] = None):
        """异步启动公网隧道"""
        if self.is_running:
            if on_ready and self.tunnel_url:
                on_ready(self.tunnel_url)
            return

        self.on_url_ready = on_ready
        self.on_error = on_error
        self._stop_event.clear()
        self.is_running = True

        logger.info(f"正在异步启动 Cloudflare Quick Tunnel (本地中继端口: {self.local_port})...")
        threading.Thread(target=self._run_tunnel, daemon=True).start()

    def _run_tunnel(self):
        cmd_path = self._get_cloudflared_path()
        if not os.path.exists(cmd_path) and cmd_path != "cloudflared":
            self.is_running = False
            logger.error("未在项目根目录找到 cloudflared.exe 组件！")
            if self.on_error:
                self.on_error("未找到 cloudflared.exe 组件！")
            return

        cmd = [cmd_path, "tunnel", "--url", f"http://127.0.0.1:{self.local_port}"]
        logger.debug(f"执行命令: {' '.join(cmd)}")
        try:
            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                creationflags=creationflags
            )

            # 读取输出日志寻找 trycloudflare.com 链接
            start_time = time.time()
            url_found = False
            while not self._stop_event.is_set():
                if self.process.poll() is not None:
                    break
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                clean_line = line.strip()
                if clean_line:
                    logger.debug(f"[cloudflared] {clean_line}")

                if not url_found:
                    match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                    if match:
                        self.tunnel_url = match.group(0)
                        url_found = True
                        logger.info("=" * 60)
                        logger.info(f"🌐 Cloudflare 全球公网隧道创建成功: {self.tunnel_url}")
                        logger.info("=" * 60)
                        if self.on_url_ready:
                            self.on_url_ready(self.tunnel_url)

                # 超时 30 秒若还未取得链接
                if not url_found and time.time() - start_time > 30:
                    logger.error("公网隧道连接超时 (30秒)")
                    if self.on_error:
                        self.on_error("公网隧道连接超时，请检查网络状况。")
                    break

        except Exception as e:
            self.is_running = False
            logger.error(f"启动 Cloudflare 隧道失败: {e}", exc_info=True)
            if self.on_error:
                self.on_error(f"启动公网隧道失败: {e}")
        finally:
            self.stop()

    def stop(self):
        """关闭公网隧道"""
        self._stop_event.set()
        self.is_running = False
        self.tunnel_url = None
        if self.process:
            logger.info("正在关闭 Cloudflare 隧道进程...")
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            logger.info("Cloudflare 隧道已终止")
