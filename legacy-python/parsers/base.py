"""
VRC-VideoTools - 解析器基础模块
定义通用数据结构与工具函数
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class VideoQuality:
    """单个清晰度选项"""
    label: str               # 显示名称，如 "1080P 高清", "720P", "原始画质"
    url: str                 # 对应直链
    quality_id: int = 0      # 平台内部清晰度标识
    size_mb: Optional[float] = None
    backup_urls: List[str] = field(default_factory=list)


@dataclass
class VideoInfo:
    """解析后的视频信息对象"""
    platform: str                    # 'bilibili' | 'douyin' | 'kuaishou'
    platform_name: str               # '哔哩哔哩' | '抖音' | '快手'
    video_id: str                    # 视频平台 ID
    title: str                       # 视频标题
    author: str                      # UP主 / 创作者
    author_avatar: str = ""          # 作者头像
    duration_sec: int = 0            # 视频时长 (秒)
    duration_str: str = "00:00"      # 格式化时长 (MM:SS 或 HH:MM:SS)
    cover_url: str = ""              # 封面图链接
    play_url: str = ""               # 主播放直链 (MP4/HLS)
    size_mb: Optional[float] = None  # 文件大小 (MB)
    quality: str = "默认"            # 当前画质标签
    qualities: List[VideoQuality] = field(default_factory=list)  # 可用画质列表
    raw_data: Dict[str, Any] = field(default_factory=dict)       # 原始接口数据


def format_duration(seconds: int) -> str:
    """将秒数转为 MM:SS 或 HH:MM:SS 格式"""
    if not seconds or seconds < 0:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_url(text: str) -> Optional[str]:
    """从文本中提取出第一个 http 或 https 链接"""
    if not text:
        return None
    text = text.strip()
    match = re.search(r"https?://[^\s<>\"'，。；！？]+", text)
    if match:
        url = match.group(0)
        # 去除尾部可能多匹配的标点
        url = re.sub(r"[，。；！？)\]}]+$", "", url)
        return url
    return None


def detect_platform(text: str) -> str:
    """
    根据文本或链接内容自动识别平台
    返回: 'bilibili' | 'douyin' | 'kuaishou' | 'unknown'
    """
    if not text:
        return "unknown"
    t = text.lower()
    
    # 哔哩哔哩特征
    if any(k in t for k in ["bilibili.com", "b23.tv", "bili2233.cn"]):
        return "bilibili"
    if re.search(r"bv[a-za-z0-9]{10}", t) or re.search(r"\bav\d+\b", t):
        return "bilibili"
        
    # 抖音特征
    if any(k in t for k in ["douyin.com", "iesdouyin.com", "v.douyin"]):
        return "douyin"
    if "抖音" in text and "v." in text:
        return "douyin"
        
    # 快手特征
    if any(k in t for k in ["kuaishou.com", "v.kuaishou", "video.kuaishou"]):
        return "kuaishou"
    if "快手" in text:
        return "kuaishou"
        
    return "unknown"
