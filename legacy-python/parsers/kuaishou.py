"""
VRC-VideoTools - 快手 (Kuaishou) 视频解析器
支持 v.kuaishou.com 短链、PC端长链接、APP分享文本解析
逆向逻辑：
1. 短链跟踪重定向定位 photoId
2. 自动模拟握手初始化快手风控凭证 (did / clientid / kpf)
3. 调用 GraphQL visionVideoDetail 接口解析完整视频元数据与多分辨率流
4. 备用方案：逆向解码快手客户端 INIT_STATE 凯撒混淆加密与移动端页面提取
"""

from __future__ import annotations
import re
import json
from typing import Optional, List, Dict, Any
import requests

from .base import VideoInfo, VideoQuality, extract_url, format_duration
from utils.logger import get_logger

logger = get_logger("kuaishou")


class KuaishouParser:
    """快手短视频解析器"""

    GRAPHQL_API = "https://www.kuaishou.com/graphql"
    HOME_URL = "https://www.kuaishou.com/"

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    GRAPHQL_QUERY = """
    query visionVideoDetail($photoId: String, $type: String, $page: String, $webPageArea: String) {
      visionVideoDetail(photoId: $photoId, type: $type, page: $page, webPageArea: $webPageArea) {
        status
        type
        author {
          id
          name
          headerUrl
        }
        photo {
          id
          duration
          caption
          coverUrl
          photoUrl
          photoH265Url
          manifest {
            adaptationSet {
              representation {
                id
                url
                qualityLabel
                qualityType
                height
                width
                avgBitrate
              }
            }
          }
        }
      }
    }
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Referer": "https://www.kuaishou.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._initialized_cookies = False

    def _ensure_cookies(self):
        """访问快手主页激活生成 did 及 client 凭据"""
        if self._initialized_cookies:
            return
        logger.debug("正在初始化快手会话环境与 did 凭证...")
        try:
            self.session.get(self.HOME_URL, timeout=8)
            self._initialized_cookies = True
            logger.debug(f"快手会话初始化成功，已获取 Cookies: {list(self.session.cookies.keys())}")
        except Exception as e:
            logger.warning(f"访问快手主页失败: {e}，将启用备用临时凭证")
            # 备用临时 cookie
            self.session.cookies.set("kpf", "PC_WEB", domain=".kuaishou.com")
            self.session.cookies.set("kpn", "KUAISHOU_VISION", domain=".kuaishou.com")
            self.session.cookies.set("clientid", "3", domain=".kuaishou.com")
            self.session.cookies.set("did", "web_vrc_temp_did_123456", domain=".kuaishou.com")
            self._initialized_cookies = True

    def extract_photo_id(self, input_text: str) -> Optional[str]:
        """
        从输入中提取 photoId (如 3x8z7362y3q8p84)
        """
        raw_url = extract_url(input_text) or input_text.strip()
        target = raw_url
        logger.debug(f"正在从输入提取快手 photoId: {input_text[:60]}...")

        if target.startswith("http"):
            try:
                resp = self.session.get(target, allow_redirects=True, timeout=self.timeout)
                target = str(resp.url)
                logger.debug(f"快手链接重定向目标: {target[:100]}...")
            except Exception as e:
                logger.warning(f"跟踪快手短链接异常: {e}")

        # 匹配各种快手 URL 形式中的 ID
        patterns = [
            r"/short-video/([a-zA-Z0-9_-]+)",
            r"/fw/photo/([a-zA-Z0-9_-]+)",
            r"/photo/([a-zA-Z0-9_-]+)",
            r"photoId=([a-zA-Z0-9_-]+)",
            r"([3a-zA-Z0-9]{12,24})"
        ]
        for pat in patterns:
            match = re.search(pat, target)
            if match:
                candidate = match.group(1)
                # 排除通用关键词
                if candidate not in ["graphql", "short-video", "undefined"]:
                    logger.debug(f"成功提取快手 photoId: {candidate}")
                    return candidate

        logger.warning(f"未能提取到快手 photoId: {input_text[:60]}")
        return None

    def parse(self, input_text: str) -> VideoInfo:
        """
        执行快手视频解析
        """
        photo_id = self.extract_photo_id(input_text)
        if not photo_id:
            raise ValueError("未能从输入中提取到有效的快手视频链接或 photoId！")

        logger.info(f"开始解析快手视频: photoId={photo_id}")
        self._ensure_cookies()

        # 1. 优先使用 GraphQL visionVideoDetail 接口
        try:
            logger.debug(f"尝试通过 GraphQL 接口请求视频详情...")
            video_info = self._parse_via_graphql(photo_id)
            if video_info:
                logger.info(f"✅ 快手视频 GraphQL 解析成功: 《{video_info.title}》 by {video_info.author}")
                return video_info
        except Exception as e:
            logger.warning(f"GraphQL 解析异常: {e}，尝试使用备选方案")

        # 2. 备选方案：网页页面 INIT_STATE 解密与正则提取
        try:
            logger.debug(f"尝试通过网页源码解密备选方案解析...")
            video_info = self._parse_via_web_page(photo_id)
            if video_info:
                logger.info(f"✅ 快手视频网页端解密解析成功: 《{video_info.title}》 by {video_info.author}")
                return video_info
        except Exception as e:
            logger.error(f"网页端解密解析异常: {e}", exc_info=True)

        logger.error(f"快手视频 photoId={photo_id} 解析失败")
        raise ValueError("快手视频解析失败，作品可能已被删除、设置为私密或存在风控限制！")

    def _parse_via_graphql(self, photo_id: str) -> Optional[VideoInfo]:
        """通过快手 GraphQL 接口解析"""
        payload = {
            "operationName": "visionVideoDetail",
            "variables": {
                "photoId": photo_id,
                "page": "detail",
                "webPageArea": "detail"
            },
            "query": self.GRAPHQL_QUERY
        }
        headers = {
            "Content-Type": "application/json",
            "Referer": f"https://www.kuaishou.com/short-video/{photo_id}"
        }

        resp = self.session.post(self.GRAPHQL_API, json=payload, headers=headers, timeout=self.timeout)
        logger.debug(f"GraphQL 响应状态码: HTTP {resp.status_code}")
        if resp.status_code != 200:
            return None

        res_data = resp.json()
        detail = res_data.get("data", {}).get("visionVideoDetail")
        if not detail or not detail.get("photo"):
            logger.debug(f"GraphQL 响应未包含 photo 字段")
            return None

        photo = detail["photo"]
        author = detail.get("author", {}) or {}

        title = photo.get("caption") or "快手短视频"
        author_name = author.get("name", "未知快手用户")
        author_avatar = author.get("headerUrl", "")
        cover_url = photo.get("coverUrl", "")

        duration_ms = photo.get("duration", 0)
        duration_sec = int(duration_ms / 1000) if duration_ms > 0 else 0

        # 获取可用清晰度列表
        qualities: List[VideoQuality] = []
        manifest = photo.get("manifest") or {}
        adaptation_sets = manifest.get("adaptationSet", [])

        if adaptation_sets and isinstance(adaptation_sets, list):
            reps = adaptation_sets[0].get("representation", [])
            for rep in reps:
                url = rep.get("url")
                if url:
                    qlabel = rep.get("qualityLabel") or f"{rep.get('height', '标清')}P"
                    qualities.append(
                        VideoQuality(
                            label=qlabel,
                            url=url
                        )
                    )

        main_url = photo.get("photoUrl", "")
        if not main_url and qualities:
            main_url = qualities[0].url

        if not main_url:
            return None

        if not qualities:
            qualities.append(VideoQuality(label="标准画质", url=main_url))

        return VideoInfo(
            platform="kuaishou",
            platform_name="快手",
            video_id=photo_id,
            title=title,
            author=author_name,
            author_avatar=author_avatar,
            duration_sec=duration_sec,
            duration_str=format_duration(duration_sec),
            cover_url=cover_url,
            play_url=main_url,
            quality=qualities[0].label,
            qualities=qualities,
            raw_data=detail
        )

    def _parse_via_web_page(self, photo_id: str) -> Optional[VideoInfo]:
        """逆向快手 HTML 源码提取 INIT_STATE 或视频直链"""
        url = f"https://www.kuaishou.com/short-video/{photo_id}"
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code != 200:
            return None

        # 尝试正则直接提取 mp4 直链
        video_matches = re.findall(r'"photoUrl":"(https?:\\/\\/[^"]+)"', r.text)
        if video_matches:
            play_url = video_matches[0].replace(r"\/", "/")
            caption_match = re.search(r'"caption":"([^"]+)"', r.text)
            title = caption_match.group(1) if caption_match else "快手短视频"
            return VideoInfo(
                platform="kuaishou",
                platform_name="快手",
                video_id=photo_id,
                title=title,
                author="快手用户",
                author_avatar="",
                duration_sec=0,
                duration_str="--:--",
                cover_url="",
                play_url=play_url,
                quality="标准画质",
                qualities=[VideoQuality(label="标准画质", url=play_url)],
                raw_data={}
            )

        # 尝试逆向快手 INIT_STATE 凯撒偏移加密混淆
        state_match = re.search(r"window\.INIT_STATE\s*=\s*['\"]([^'\"]+)['\"]", r.text)
        if state_match:
            try:
                encoded = state_match.group(1)
                # 快手传统凯撒偏移字符解码器 (ASCII ord - 1)
                decoded = "".join(chr(ord(c) - 1) for c in encoded)
                state_json = json.loads(decoded)
                cur_photo = state_json.get("photo", {})
                if cur_photo:
                    play_url = cur_photo.get("photoUrl", "")
                    title = cur_photo.get("caption", "快手短视频")
                    author = cur_photo.get("userName", "快手用户")
                    cover = cur_photo.get("coverUrl", "")
                    if play_url:
                        return VideoInfo(
                            platform="kuaishou",
                            platform_name="快手",
                            video_id=photo_id,
                            title=title,
                            author=author,
                            author_avatar="",
                            duration_sec=0,
                            duration_str="--:--",
                            cover_url=cover,
                            play_url=play_url,
                            quality="标准画质",
                            qualities=[VideoQuality(label="标准画质", url=play_url)],
                            raw_data=cur_photo
                        )
            except Exception as ex:
                logger.debug(f"快手 INIT_STATE 凯撒解密未命中: {ex}")

        return None
