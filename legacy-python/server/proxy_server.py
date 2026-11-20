"""
VRC-VideoTools - VRChat 流媒体本地代理中继服务器
解决 VRChat (AVPro Video / Unity VideoPlayer) 播放 Bilibili / 抖音 / 快手 时的 403 Forbidden 及防盗链限制
功能特性：
1. 伪造各平台对应的 Referer 与 User-Agent
2. 完整支持 HTTP 206 Partial Content (Range 请求)，保障 VRChat 拖动进度条 / 快进快退 (Seeking) 丝滑流畅
3. 支持 本机回环模式 (127.0.0.1) 与 局域网广播模式 (LAN IP)
4. 内置 Web HTML5 播放器 (/player)，可在浏览器中快速验证视频播放状态
"""

from __future__ import annotations
import http.server
import socketserver
import threading
import urllib.parse
import socket
from typing import Optional
import requests

from utils.logger import get_logger

logger = get_logger("proxy")


class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    """流媒体转发处理器"""

    def log_message(self, format, *args):
        # 统一输出至 DEBUG 日志系统
        logger.debug(f"HTTP {self.client_address[0]} - {format % args}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        # 1. 健康检查接口
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"VRC-VideoTools Proxy Server is Running OK")
            return

        # 2. 内置 Web 测试播放器
        if path == "/player":
            target_url = qs.get("url", [None])[0]
            platform = qs.get("platform", ["unknown"])[0]
            if not target_url:
                self.send_error(400, "Missing target url")
                return

            logger.info(f"客户端 {self.client_address[0]} 访问内置 Web 测试播放器, 平台: {platform}")
            stream_src = f"/stream.mp4?url={urllib.parse.quote(target_url)}&platform={platform}"
            html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VRC-VideoTools 播放测试</title>
    <style>
        body {{
            margin: 0;
            background-color: #0f111a;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }}
        .player-card {{
            background: #1a1c23;
            border: 1px solid #2d3139;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            max-width: 900px;
            width: 90%;
            text-align: center;
        }}
        h2 {{
            margin-top: 0;
            color: #89b4fa;
        }}
        video {{
            width: 100%;
            max-height: 540px;
            border-radius: 8px;
            background: #000;
            outline: none;
        }}
        .tips {{
            margin-top: 15px;
            font-size: 13px;
            color: #a6adc8;
        }}
    </style>
</head>
<body>
    <div class="player-card">
        <h2>VRC-VideoTools 视频流代理播放验证</h2>
        <video controls autoplay preload="auto">
            <source src="{stream_src}" type="video/mp4">
            您的浏览器不支持 HTML5 视频播放
        </video>
        <div class="tips">
            当前视频正在通过 VRC-VideoTools 本地代理中继流式传输 (已注入对应防盗链请求头)。<br>
            若本页面可正常播放并拖动进度条，则说明 VRChat 播放器同样可正常播放！
        </div>
    </div>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        # 3. 核心流媒体中继接口 (/stream 或 /stream.mp4)
        if path in ("/stream", "/stream.mp4"):
            target_url = qs.get("url", [None])[0]
            platform = qs.get("platform", ["unknown"])[0]

            if not target_url:
                logger.warning(f"客户端 {self.client_address[0]} 请求缺失 url 参数")
                self.send_error(400, "Missing 'url' parameter")
                return

            client_range = self.headers.get("Range", "Full")
            logger.debug(f"[中继请求] 来自 {self.client_address[0]} -> 平台={platform} Range={client_range}")

            # 根据平台或域名智能分配防盗链 Referer
            req_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                )
            }

            if platform == "bilibili" or "bilivideo.com" in target_url or "bilibili.com" in target_url:
                req_headers["Referer"] = "https://www.bilibili.com/"
            elif platform == "douyin" or "douyinvod.com" in target_url or "douyin.com" in target_url:
                req_headers["Referer"] = "https://www.douyin.com/"
            elif platform == "kuaishou" or "kwaicdn.com" in target_url or "kuaishou.com" in target_url:
                req_headers["Referer"] = "https://www.kuaishou.com/"

            # 转发 VRChat / 浏览器的 Range 头 (保证拖动进度条与分片加载)
            if "Range" in self.headers:
                req_headers["Range"] = self.headers["Range"]

            try:
                with requests.get(target_url, headers=req_headers, stream=True, timeout=20) as resp:
                    logger.debug(f"[上游响应] CDN 返回 HTTP {resp.status_code}, 内容长度: {resp.headers.get('Content-Length', '未知')} 字节, 类型: {resp.headers.get('Content-Type')}")
                    self.send_response(resp.status_code)

                    # 转发关键响应头
                    forward_headers = [
                        "Content-Type",
                        "Content-Length",
                        "Content-Range",
                        "Accept-Ranges",
                        "ETag",
                        "Last-Modified",
                    ]
                    for h in forward_headers:
                        if h in resp.headers:
                            self.send_header(h, resp.headers[h])

                    # 允许跨域
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Allow-Headers", "*")
                    self.end_headers()

                    # 分块写入客户端
                    chunk_size = 64 * 1024  # 64KB
                    total_sent = 0
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        self.wfile.write(chunk)
                        total_sent += len(chunk)
                    logger.debug(f"[中继完成] 向 {self.client_address[0]} 传输完毕: {round(total_sent/1024/1024, 2)} MB")
            except (ConnectionResetError, BrokenPipeError):
                logger.debug(f"[客户端断开] 客户端 {self.client_address[0]} 已切换分片或停止播放")
            except Exception as e:
                logger.error(f"[中继异常] 转发视频流失败: {e}", exc_info=True)
                try:
                    self.send_error(502, f"Proxy stream error: {e}")
                except Exception:
                    pass
            return

        # 默认 404
        self.send_error(404, "Not Found")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """支持多线程并发的分片传输 HTTP 服务器"""
    daemon_threads = True
    allow_reuse_address = True


class VRCProxyServer:
    """VRChat 本地代理服务生命周期管理器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 9527):
        self.host = host
        self.port = port
        self.server: Optional[ThreadedHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self) -> bool:
        """启动代理服务"""
        if self.is_running:
            return True
        try:
            self.server = ThreadedHTTPServer((self.host, self.port), StreamProxyHandler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.is_running = True
            lan_ip = self.get_local_ip()
            logger.info("=" * 60)
            logger.info(f"🚀 VRChat 流媒体代理中继已成功监听端口: {self.port}")
            logger.info(f" - 本地访问: http://127.0.0.1:{self.port}")
            logger.info(f" - 局域网物理访问: http://{lan_ip}:{self.port}")
            logger.info("=" * 60)
            return True
        except Exception as e:
            self.is_running = False
            logger.error(f"❌ 启动本地代理服务失败 (端口 {self.port}): {e}", exc_info=True)
            return False

    def stop(self):
        """停止代理服务"""
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                logger.warning(f"关闭代理服务异常: {e}")
        self.is_running = False
        self.server = None
        self.thread = None
        logger.info("VRChat 流媒体代理服务已停止")

    @staticmethod
    def get_local_ip() -> str:
        """获取局域网真实 IPv4 地址 (智能优先物理局域网网卡，过滤 TUN/VPN 虚拟网卡)"""
        candidates = []
        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                if not ip.startswith("127.") and not ip.startswith("169.254."):
                    candidates.append(ip)
        except Exception:
            pass

        # 优先物理局域网常见段 192.168.x.x
        for ip in candidates:
            if ip.startswith("192.168."):
                return ip
        # 其次 10.x.x.x
        for ip in candidates:
            if ip.startswith("10."):
                return ip
        # 其次 172.16~31 (排除典型 VPN 网关)
        for ip in candidates:
            if not ip.startswith("172.18."):
                return ip
        if candidates:
            return candidates[0]

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_stream_url(
        self,
        target_url: str,
        platform: str = "unknown",
        mode: str = "local",
        custom_host: str = "",
        tunnel_url: str = ""
    ) -> str:
        """
        生成 VRChat 可直接粘贴播放的代理链接
        :param mode: 'tunnel' (公网穿透) | 'custom' (自定义公网域名/IP) | 'lan' (局域网) | 'local' (本机回环)
        """
        encoded = urllib.parse.quote(target_url)

        if mode == "tunnel" and tunnel_url:
            base = tunnel_url.rstrip("/")
            return f"{base}/stream.mp4?url={encoded}&platform={platform}"

        if mode == "custom" and custom_host:
            host_clean = custom_host.strip().rstrip("/")
            if not host_clean.startswith("http://") and not host_clean.startswith("https://"):
                host_clean = f"http://{host_clean}"
            return f"{host_clean}/stream.mp4?url={encoded}&platform={platform}"

        if mode == "lan":
            host = self.get_local_ip()
            return f"http://{host}:{self.port}/stream.mp4?url={encoded}&platform={platform}"

        # 默认本机 127.0.0.1
        return f"http://127.0.0.1:{self.port}/stream.mp4?url={encoded}&platform={platform}"

    def get_player_url(self, target_url: str, platform: str = "unknown") -> str:
        """生成浏览器测试播放链接"""
        encoded = urllib.parse.quote(target_url)
        return f"http://127.0.0.1:{self.port}/player?url={encoded}&platform={platform}"
