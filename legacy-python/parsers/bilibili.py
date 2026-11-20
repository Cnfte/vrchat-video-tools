"""
VRC-VideoTools - 哔哩哔哩 (Bilibili) 视频解析器
支持 BV号、AV号、b23.tv 短链、完整视频链接、分P视频解析
逆向逻辑：调用官方公开 API 获取视频元数据与播放直链 (fnval=1 纯 MP4 混流模式，完美契合 VRChat AVPro)
"""

from __future__ import annotations
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs
import requests

from .base import VideoInfo, VideoQuality, extract_url, format_duration
from utils.logger import get_logger

logger = get_logger("bilibili")


class BilibiliParser:
    """哔哩哔哩视频解析器"""

    VIEW_API = "https://api.bilibili.com/x/web-interface/view"
    PLAY_API = "https://api.bilibili.com/x/player/playurl"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def extract_id_and_page(self, input_text: str) -> tuple[Optional[str], Optional[str], int]:
        """
        从输入文本中解析出 (bvid, aid, p)
        支持短链接重定向追踪
        """
        raw_url = extract_url(input_text) or input_text.strip()
        target_url = raw_url
        logger.debug(f"正在从输入提取 B站 标识符: {input_text[:60]}...")

        # 如果是 b23.tv 短链，跟踪重定向获取完整链接
        if "b23.tv" in target_url:
            logger.debug(f"检测到 b23.tv 短链，正在追踪重定向: {target_url}")
            try:
                resp = self.session.get(target_url, allow_redirects=True, timeout=self.timeout)
                target_url = str(resp.url)
                logger.debug(f"b23.tv 短链重定向至: {target_url}")
            except Exception as e:
                logger.warning(f"追踪短链失败: {e}")

        # 解析分P参数 (如 ?p=2)
        parsed = urlparse(target_url)
        qs = parse_qs(parsed.query)
        page_num = 1
        if "p" in qs and qs["p"][0].isdigit():
            page_num = int(qs["p"][0])

        # 匹配 BVID (BV1xx411c7mD)
        bv_match = re.search(r"(BV[a-zA-Z0-9]{10})", target_url, re.I)
        if bv_match:
            bvid = bv_match.group(1)
            logger.debug(f"成功识别 BVID: {bvid}, 分P: P{page_num}")
            return bvid, None, page_num

        # 匹配 AVID (av170001)
        av_match = re.search(r"\bav(\d+)\b", target_url, re.I)
        if av_match:
            aid = av_match.group(1)
            logger.debug(f"成功识别 AVID: {aid}, 分P: P{page_num}")
            return None, aid, page_num

        # 纯纯数字输入视作 avid
        if target_url.isdigit():
            logger.debug(f"纯数字输入识别为 AVID: {target_url}")
            return None, target_url, page_num

        logger.warning(f"未能从输入中识别出有效的 BVID 或 AVID")
        return None, None, page_num

    def parse(self, input_text: str) -> VideoInfo:
        """
        执行解析并返回 VideoInfo
        """
        bvid, aid, page_num = self.extract_id_and_page(input_text)
        if not bvid and not aid:
            raise ValueError("未能识别出有效的哔哩哔哩视频链接或 BV/AV 号！")

        logger.info(f"开始解析哔哩哔哩视频元数据: BVID={bvid or 'None'} AID={aid or 'None'} P={page_num}")

        # 1. 获取视频基本信息
        params: Dict[str, Any] = {}
        if bvid:
            params["bvid"] = bvid
        else:
            params["aid"] = aid

        try:
            view_resp = self.session.get(self.VIEW_API, params=params, timeout=self.timeout)
            view_resp.raise_for_status()
            view_data = view_resp.json()
        except Exception as e:
            logger.error(f"请求 B站 view 接口失败: {e}", exc_info=True)
            raise RuntimeError(f"请求哔哩哔哩接口失败: {e}")

        if view_data.get("code") != 0:
            err_msg = view_data.get("message", "未知错误")
            logger.error(f"B站 view 接口返回错误: [{view_data.get('code')}] {err_msg}")
            raise ValueError(f"哔哩哔哩接口错误 [{view_data.get('code')}]: {err_msg}")

        vdata = view_data["data"]
        resolved_bvid = vdata.get("bvid", bvid or "")
        title = vdata.get("title", "未知标题")
        cover_url = vdata.get("pic", "")
        author_name = vdata.get("owner", {}).get("name", "未知UP主")
        author_avatar = vdata.get("owner", {}).get("face", "")
        total_duration = vdata.get("duration", 0)

        # 确认目标 cid 和标题 (考虑分P)
        pages = vdata.get("pages", [])
        if pages and 1 <= page_num <= len(pages):
            target_page = pages[page_num - 1]
            cid = target_page["cid"]
            part_title = target_page.get("part", "")
            if len(pages) > 1 and part_title:
                title = f"{title} (P{page_num} {part_title})"
            target_duration = target_page.get("duration", total_duration)
        else:
            cid = vdata.get("cid", 0)
            target_duration = total_duration

        if not cid:
            raise ValueError("获取视频核心流 ID (cid) 失败！")

        logger.debug(f"已获取视频基本信息: 《{title}》 UP主: {author_name}, 时长: {target_duration}s, cid={cid}")

        # 2. 获取播放直链
        # 使用 platform=html5 & high_quality=1 请求免Referer鉴权Token直链
        play_params = {
            "bvid": resolved_bvid,
            "cid": cid,
            "qn": 80,             # 1080P/720P 高清
            "fnval": 1,           # 核心：纯 MP4 混流模式 (音视频合一)
            "fnver": 0,
            "fourk": 1,
            "platform": "html5",  # 注入 html5 令牌，生成免 Referer 防盗链授权直链
            "high_quality": 1,
        }

        logger.debug(f"正在向 B站 playurl 接口申请免防盗链 MP4 直链...")
        try:
            play_resp = self.session.get(self.PLAY_API, params=play_params, timeout=self.timeout)
            play_resp.raise_for_status()
            play_data = play_resp.json()
        except Exception as e:
            logger.error(f"请求 B站 playurl 失败: {e}", exc_info=True)
            raise RuntimeError(f"请求视频播放直链失败: {e}")

        if play_data.get("code") != 0:
            err_msg = play_data.get("message", "未知错误")
            logger.error(f"B站 playurl 接口返回错误: [{play_data.get('code')}] {err_msg}")
            raise ValueError(f"获取播放地址失败 [{play_data.get('code')}]: {err_msg}")

        presult = play_data.get("data", {})
        durl_list = presult.get("durl", [])
        if not durl_list:
            raise ValueError("未能解析出可播放的 MP4 视频直链地址！")

        # 提取最高画质直链与备选画质
        main_durl = durl_list[0]
        play_url = main_durl["url"]
        size_bytes = main_durl.get("size", 0)
        size_mb = round(size_bytes / 1024 / 1024, 2) if size_bytes > 0 else None

        # 映射画质描述
        qn_map = {
            120: "4K 超高清",
            116: "1080P 60帧",
            80: "1080P 高清 (免Referer)",
            64: "720P 高清 (免Referer)",
            32: "480P 清晰",
            16: "360P 流畅",
        }
        current_qn = presult.get("quality", 80)
        quality_label = qn_map.get(current_qn, f"高清 ({current_qn}P)")

        # 构建 VRChat 免防盗链优选直链 (使用 upcdnbda2 宽松鉴权节点，彻底杜绝 Forbid_code: 020200 与 UA/Referer 拦截)
        zero_403_url = re.sub(r'https?://[^/]+/', 'https://upos-sz-upcdnbda2.bilivideo.com/', play_url)

        qualities: List[VideoQuality] = []
        # 1. 首选：VRChat 免中继直连 (零403)
        qualities.append(
            VideoQuality(
                label=f"🟢 {quality_label} (VRChat免中继直连 · 零403 · 推荐)",
                url=zero_403_url,
                size_mb=size_mb
            )
        )
        # 2. 官方原生主线路
        qualities.append(
            VideoQuality(
                label=f"⚪ {quality_label} (官方原生线路)",
                url=play_url,
                size_mb=size_mb
            )
        )

        # 3. 备选镜像线路
        for backup_idx, backup_url in enumerate(main_durl.get("backup_url") or [], start=1):
            qualities.append(
                VideoQuality(
                    label=f"⚪ {quality_label} (备用线路 {backup_idx})",
                    url=backup_url,
                    size_mb=size_mb
                )
            )

        best_quality = qualities[0]
        logger.info(f"✅ B站视频解析成功: 《{title}》 [{quality_label}] 时长: {format_duration(target_duration)} 大小: {size_mb or '动态'}MB")

        return VideoInfo(
            platform="bilibili",
            platform_name="哔哩哔哩",
            video_id=resolved_bvid,
            title=title,
            author=author_name,
            author_avatar=author_avatar,
            duration_sec=target_duration,
            duration_str=format_duration(target_duration),
            cover_url=cover_url,
            play_url=best_quality.url,
            size_mb=size_mb,
            quality=best_quality.label,
            qualities=qualities,
            raw_data=vdata
        )
