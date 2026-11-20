"""
VRC-VideoTools 解析器模块包
包含统一智能解析入口与各平台独立解析器
"""

from __future__ import annotations
from typing import Optional

from .base import VideoInfo, VideoQuality, detect_platform, extract_url, format_duration
from .bilibili import BilibiliParser
from .douyin import DouyinParser
from .kuaishou import KuaishouParser
from utils.logger import get_logger

logger = get_logger("unified")


class UnifiedParser:
    """统一智能解析器"""

    def __init__(self, timeout: int = 15):
        self.bilibili_parser = BilibiliParser(timeout=timeout)
        self.douyin_parser = DouyinParser(timeout=timeout)
        self.kuaishou_parser = KuaishouParser(timeout=timeout)

    def parse(self, input_text: str, platform_hint: Optional[str] = None) -> VideoInfo:
        """
        自动或指定平台进行视频解析
        :param input_text: 包含视频链接或分享文本的字符串
        :param platform_hint: 可选 'bilibili' | 'douyin' | 'kuaishou' | 'auto'
        """
        if not input_text or not input_text.strip():
            raise ValueError("请输入要解析的视频链接或分享文本！")

        detected = detect_platform(input_text)
        target_platform = platform_hint if platform_hint and platform_hint != "auto" else detected
        logger.info(f"统一解析器接收任务 | 提示模式: {platform_hint} | 智能检测结果: {detected} | 最终分发平台: {target_platform}")

        if target_platform == "bilibili":
            return self.bilibili_parser.parse(input_text)
        elif target_platform == "douyin":
            return self.douyin_parser.parse(input_text)
        elif target_platform == "kuaishou":
            return self.kuaishou_parser.parse(input_text)
        else:
            logger.warning("未能根据特征匹配到目标平台，启动顺序容灾重试...")
            errors = []
            for name, p_code, parser in [
                ("哔哩哔哩", "bilibili", self.bilibili_parser),
                ("抖音", "douyin", self.douyin_parser),
                ("快手", "kuaishou", self.kuaishou_parser),
            ]:
                try:
                    logger.debug(f"尝试按 [{name}] 规则解析...")
                    return parser.parse(input_text)
                except Exception as e:
                    logger.debug(f"[{name}] 容灾解析失败: {e}")
                    errors.append(f"{name}: {e}")

            err_msg = "未能识别该链接归属的平台，且自动解析失败。\n" + "\n".join(errors)
            logger.error(err_msg)
            raise ValueError(err_msg)


__all__ = [
    "VideoInfo",
    "VideoQuality",
    "detect_platform",
    "extract_url",
    "format_duration",
    "BilibiliParser",
    "DouyinParser",
    "KuaishouParser",
    "UnifiedParser",
]
