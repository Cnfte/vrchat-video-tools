package parsers

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

// VideoQuality 视频画质/线路定义
type VideoQuality struct {
	Label  string  `json:"label"`
	URL    string  `json:"url"`
	SizeMB float64 `json:"size_mb"`
}

// VideoInfo 统一视频元数据结构体
type VideoInfo struct {
	Platform     string         `json:"platform"`      // bilibili, douyin, kuaishou
	PlatformName string         `json:"platform_name"` // 哔哩哔哩, 抖音, 快手
	VideoID      string         `json:"video_id"`
	Title        string         `json:"title"`
	Author       string         `json:"author"`
	AuthorAvatar string         `json:"author_avatar"`
	DurationSec  int            `json:"duration_sec"`
	DurationStr  string         `json:"duration_str"`
	CoverURL     string         `json:"cover_url"`
	PlayURL      string         `json:"play_url"` // 首选全员直链 (零403)
	SizeMB       float64        `json:"size_mb"`
	Quality      string         `json:"quality"`
	Qualities    []VideoQuality `json:"qualities"`
}

var urlRegex = regexp.MustCompile(`https?://[^\s，,。；;]+`)

// ExtractURL 从混合文本中提取首个有效 HTTP/HTTPS 链接
func ExtractURL(text string) string {
	match := urlRegex.FindString(text)
	if match != "" {
		return strings.TrimRight(match, ",.。；;!！?？")
	}
	return strings.TrimSpace(text)
}

// FormatDuration 格式化秒数为 MM:SS 或 HH:MM:SS
func FormatDuration(seconds int) string {
	if seconds <= 0 {
		return "00:00"
	}
	h := seconds / 3600
	m := (seconds % 3600) / 60
	s := seconds % 60
	if h > 0 {
		return fmt.Sprintf("%02d:%02d:%02d", h, m, s)
	}
	return fmt.Sprintf("%02d:%02d", m, s)
}

var (
	biliRegex     = regexp.MustCompile(`(?i)(bilibili\.com|b23\.tv|bili2233\.cn|\bBV1[a-zA-Z0-9]{9}\b|\bav\d+\b)`)
	douyinRegex   = regexp.MustCompile(`(?i)(douyin\.com|iesdouyin\.com|v\.douyin\.com|amemv\.com|snssdk\.com)`)
	kuaishouRegex = regexp.MustCompile(`(?i)(kuaishou\.com|kwai\.com|v\.kuaishou\.com|gifshow\.com|chenzhongtech\.com)`)
)

// DetectPlatform 智能检测平台
func DetectPlatform(rawText string) string {
	if biliRegex.MatchString(rawText) {
		return "bilibili"
	}
	if douyinRegex.MatchString(rawText) {
		return "douyin"
	}
	if kuaishouRegex.MatchString(rawText) {
		return "kuaishou"
	}
	return "unknown"
}

// ParseURLQuery 安全提取 Query 参数
func ParseURLQuery(rawURL string) (url.Values, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return nil, err
	}
	return u.Query(), nil
}
