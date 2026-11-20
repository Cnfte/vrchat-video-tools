"""
VRC-VideoTools - 入口程序
运行方式：
1. 双击运行或在终端中运行 `python main.py` 启动 GUI 桌面应用 (后台自动记录详细调试日志)
2. 命令行模式：`python main.py <视频链接>` 直接解析输出直链与代理链接
"""

from __future__ import annotations
import sys
import argparse
import platform

# 确保在 Windows 控制台 (GBK) 下安全输出 UTF-8 字符及 Emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from utils.logger import setup_logger, get_logger, LOG_FILE
from ui.app_window import run_gui
from parsers import UnifiedParser
from server.proxy_server import VRCProxyServer


def run_cli(target_url: str):
    """命令行运行模式"""
    logger = get_logger("cli")
    logger.info("=" * 60)
    logger.info(f"🎬 启动命令行视频解析模式，输入内容: {target_url}")
    logger.info("=" * 60)

    parser = UnifiedParser()
    try:
        info = parser.parse(target_url)
    except Exception as e:
        logger.error(f"❌ 视频解析失败: {e}", exc_info=True)
        sys.exit(1)

    proxy = VRCProxyServer(port=9527)
    vrc_local = proxy.get_stream_url(info.play_url, platform=info.platform, mode="local")
    vrc_lan = proxy.get_stream_url(info.play_url, platform=info.platform, mode="lan")

    logger.info(f"✅ 解析成功: [{info.platform_name}] {info.title}")
    logger.info(f"作者: {info.author} | 时长: {info.duration_str} | 大小: {info.size_mb or '动态'} MB")
    logger.info(f"官方 CDN 直链: {info.play_url}")
    logger.info(f"VRChat 本地中继: {vrc_local}")
    logger.info(f"VRChat 局域网中继: {vrc_lan}")

    # 同时友好打印给控制台
    print("\n" + "=" * 60)
    print("🎬 VRC-VideoTools 命令行快速解析结果")
    print("=" * 60)
    print(f"[+] 视频信息:")
    print(f"  - 平台: {info.platform_name}")
    print(f"  - 标题: {info.title}")
    print(f"  - 作者: {info.author}")
    print(f"  - 时长: {info.duration_str}")
    if info.size_mb:
        print(f"  - 大小: {info.size_mb} MB")

    print("\n[+] 🟢 官方全员同步直链 (免代理 · 所有人可直接同步播放):")
    print(f"  - {info.play_url}")

    print("\n[+] ⚪ VRChat 专用中继链接 (需本地代理服务运行在 9527 端口):")
    print(f"  - 本机链接: {vrc_local}")
    print(f"  - 局域网链接: {vrc_lan}")
    print("=" * 60 + "\n")


def main():
    # 启动后台全局详细日志
    logger = setup_logger()
    logger.info(f"系统运行环境: Python {sys.version.split()[0]} on {platform.system()} {platform.release()}")
    logger.info(f"调试日志文件已激活: {LOG_FILE}")

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        run_cli(sys.argv[1])
    else:
        arg_parser = argparse.ArgumentParser(description="VRC-VideoTools 视频解析与流媒体中继工具")
        arg_parser.add_argument("--url", "-u", type=str, help="视频链接或分享文本 (CLI模式)")
        args = arg_parser.parse_args()

        if args.url:
            run_cli(args.url)
        else:
            logger.info("正在启动 GUI 桌面应用界面...")
            run_gui()


if __name__ == "__main__":
    main()
