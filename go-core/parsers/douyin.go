package parsers

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	douyinAppUA = "com.ss.android.ugc.aweme/100401 (Linux; U; Android 10; zh_CN; MI 9; Build/QKQ1.190825.002; Cronet/TTNetVersion:5f401f46 2020-04-23 QuicVersion:47946d2a 2020-04-09)"
	douyinWebUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

var (
	douyinVideoIDRegexes = []*regexp.Regexp{
		regexp.MustCompile(`/(?:video|note)/(\d{15,25})`),
		regexp.MustCompile(`[?&](?:modal_id|aweme_id|item_id)=(\d{15,25})`),
		regexp.MustCompile(`(\d{18,20})`),
	}
)

type DouyinParser struct {
	client           *http.Client
	noRedirectClient *http.Client
}

func NewDouyinParser() *DouyinParser {
	transport := &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 20,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression:  false,
		ForceAttemptHTTP2:   true,
	}
	return &DouyinParser{
		client: &http.Client{
			Transport: transport,
			Timeout:   10 * time.Second,
		},
		noRedirectClient: &http.Client{
			Transport: transport,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
			Timeout: 5 * time.Second,
		},
	}
}

// ExtractVideoID 从任意分享文本或短链中提取纯数字 ID
func (p *DouyinParser) ExtractVideoID(inputText string) (string, error) {
	rawURL := ExtractURL(inputText)
	if rawURL == "" {
		rawURL = strings.TrimSpace(inputText)
	}

	// 纯数字判断
	if len(rawURL) >= 15 && len(rawURL) <= 25 && regexp.MustCompile(`^\d+$`).MatchString(rawURL) {
		return rawURL, nil
	}

	target := rawURL
	if strings.HasPrefix(target, "http") {
		// 1. 发起不自动重定向探测，捕获 302 Location
		req, err := http.NewRequest("GET", target, nil)
		if err == nil {
			req.Header.Set("User-Agent", douyinWebUA)
			resp, err := p.noRedirectClient.Do(req)
			if err == nil {
				resp.Body.Close()
				loc := resp.Header.Get("Location")
				if loc != "" {
					for _, reg := range douyinVideoIDRegexes {
						if m := reg.FindStringSubmatch(loc); len(m) > 1 {
							return m[1], nil
						}
					}
					target = loc
				}
			}
		}

		// 2. 完整重定向链追踪
		reqFull, err := http.NewRequest("GET", target, nil)
		if err == nil {
			reqFull.Header.Set("User-Agent", douyinWebUA)
			respFull, err := p.client.Do(reqFull)
			if err == nil {
				respFull.Body.Close()
				finalURL := respFull.Request.URL.String()
				for _, reg := range douyinVideoIDRegexes {
					if m := reg.FindStringSubmatch(finalURL); len(m) > 1 {
						return m[1], nil
					}
				}
			}
		}
	}

	// 3. 正则扫描原文本
	for _, reg := range douyinVideoIDRegexes {
		if m := reg.FindStringSubmatch(target); len(m) > 1 {
			return m[1], nil
		}
	}

	return "", errors.New("未能从输入中提取到有效的抖音视频链接或 ID")
}

// Parse 执行抖音作品解析
func (p *DouyinParser) Parse(inputText string) (*VideoInfo, error) {
	videoID, err := p.ExtractVideoID(inputText)
	if err != nil {
		return nil, err
	}

	// 1. 核心首选：移动端 Feed API (免代理/免WAF/零403)
	aweme, err := p.fetchFromMobileFeed(videoID)
	if err != nil || aweme == nil {
		// 2. 备用：Web Detail 官方接口
		aweme, err = p.fetchFromWebDetail(videoID)
	}

	if err != nil || aweme == nil {
		return nil, fmt.Errorf("抖音接口未返回有效视频数据: %v", err)
	}

	// 提取视频元数据
	title := strings.TrimSpace(aweme.Desc)
	if title == "" {
		title = "抖音短视频"
	}
	authorName := aweme.Author.Nickname
	if authorName == "" {
		authorName = "抖音创作者"
	}
	authorAvatar := ""
	if len(aweme.Author.AvatarThumb.URLList) > 0 {
		authorAvatar = aweme.Author.AvatarThumb.URLList[0]
	}

	durationSec := int(math.Round(float64(aweme.Video.Duration) / 1000.0))
	coverURL := ""
	if len(aweme.Video.Cover.URLList) > 0 {
		coverURL = aweme.Video.Cover.URLList[0]
	}

	// 3. 解析 Cold CDN 免防盗链冷流 (无 Referer 限制，VRChat 免中继零 403)
	videoURI := aweme.Video.PlayAddr.URI

	// 极速高并发并发探测：720P / 540P / 原画 协同探测，毫秒级响应
	var (
		hd720URL  string
		hd720Size float64
		sd540URL  string
		sd540Size float64
		rawURL    string
		rawSize   float64
		wg        sync.WaitGroup
	)

	wg.Add(3)
	go func() {
		defer wg.Done()
		hd720URL, hd720Size = p.resolveColdCDN(videoURI, "720p")
	}()
	go func() {
		defer wg.Done()
		sd540URL, sd540Size = p.resolveColdCDN(videoURI, "540p")
	}()
	go func() {
		defer wg.Done()
		rawURL, rawSize = p.resolveColdCDN(videoURI, "default&improve_bitrate=1")
	}()
	wg.Wait()

	var qualities []VideoQuality
	// 1. 首选推荐：720P 高清 (VRChat 流畅首选，体积适中约 3-15MB，秒开不卡)
	if hd720URL != "" {
		qualities = append(qualities, VideoQuality{
			Label:  "720P 高清 (免防盗链 · 流畅推荐)",
			URL:    hd720URL,
			SizeMB: hd720Size,
		})
	}

	// 2. 540P 标清 (极速秒开)
	if sd540URL != "" && sd540URL != hd720URL {
		qualities = append(qualities, VideoQuality{
			Label:  "540P 标清 (免防盗链 · 极速缓冲)",
			URL:    sd540URL,
			SizeMB: sd540Size,
		})
	}

	// 3. 原画超清 (高码率，文件较大)
	if rawURL != "" && rawURL != hd720URL {
		qualities = append(qualities, VideoQuality{
			Label:  "1080P 原画 (免防盗链 · 高码率)",
			URL:    rawURL,
			SizeMB: rawSize,
		})
	}

	// 4. 提取 play_addr 中的免防盗链官方 CDN 直链 (如 365yg.com / douyinvod.com 冷流)
	for idx, directURL := range aweme.Video.PlayAddr.URLList {
		if directURL != hd720URL && directURL != rawURL && !strings.Contains(directURL, "playwm") {
			szMB := math.Round(float64(aweme.Video.PlayAddr.DataSize)/1024/1024*100) / 100
			qualities = append(qualities, VideoQuality{
				Label:  fmt.Sprintf("官方直链线路 %d (免防盗链)", idx+1),
				URL:    directURL,
				SizeMB: szMB,
			})
		}
	}

	// 若没有获取到画质，使用移动端路由地址兜底
	if len(qualities) == 0 && videoURI != "" {
		fallbackURL := fmt.Sprintf("https://aweme.snssdk.com/aweme/v1/play/?video_id=%s&ratio=720p", videoURI)
		qualities = append(qualities, VideoQuality{
			Label:  "720P 免防盗链直链 (直连推荐)",
			URL:    fallbackURL,
			SizeMB: 0,
		})
	}

	if len(qualities) == 0 {
		return nil, errors.New("未能提取到可播放的视频直链地址")
	}

	best := qualities[0]
	return &VideoInfo{
		Platform:     "douyin",
		PlatformName: "抖音",
		VideoID:      videoID,
		Title:        title,
		Author:       authorName,
		AuthorAvatar: authorAvatar,
		DurationSec:  durationSec,
		DurationStr:  FormatDuration(durationSec),
		CoverURL:     coverURL,
		PlayURL:      best.URL,
		SizeMB:       best.SizeMB,
		Quality:      best.Label,
		Qualities:    qualities,
	}, nil
}

// fetchFromMobileFeed 优先通过移动端 Feed 接口获取视频信息 (免代理/零403)
func (p *DouyinParser) fetchFromMobileFeed(videoID string) (*douyinAwemeDetail, error) {
	reqURL := fmt.Sprintf("https://aweme.snssdk.com/aweme/v1/feed/?aweme_id=%s&count=1", videoID)
	req, err := http.NewRequest("GET", reqURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", douyinAppUA)

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("feed 响应 HTTP %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var res douyinFeedResponse
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, err
	}

	for _, item := range res.AwemeList {
		if item.AwemeID == videoID {
			return &item, nil
		}
	}
	if len(res.AwemeList) > 0 {
		return &res.AwemeList[0], nil
	}

	return nil, errors.New("移动端 Feed 接口未返回作品数据")
}

// fetchFromWebDetail 降级备用：Web Detail 官方接口
func (p *DouyinParser) fetchFromWebDetail(videoID string) (*douyinAwemeDetail, error) {
	apiURL := "https://www.douyin.com/aweme/v1/web/aweme/detail/"
	params := url.Values{}
	params.Set("aweme_id", videoID)
	params.Set("aid", "6383")
	params.Set("device_platform", "webapp")
	params.Set("browser_language", "zh-CN")

	fullURL := apiURL + "?" + params.Encode()
	req, err := http.NewRequest("GET", fullURL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", douyinWebUA)
	req.Header.Set("Referer", fmt.Sprintf("https://www.douyin.com/video/%s", videoID))
	req.Header.Set("Accept", "application/json, text/plain, */*")

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("web detail 响应 HTTP %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var res struct {
		AwemeDetail *douyinAwemeDetail `json:"aweme_detail"`
	}
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, err
	}
	if res.AwemeDetail == nil {
		return nil, errors.New("Web 详情接口返回空数据")
	}
	return res.AwemeDetail, nil
}

// resolveColdCDN 解析 snssdk 302 重定向后的 Cold CDN 真实播放地址 (拦截 302 Location 极速获取，免下载流)
func (p *DouyinParser) resolveColdCDN(videoURI string, ratio string) (string, float64) {
	if videoURI == "" {
		return "", 0
	}
	if ratio == "" {
		ratio = "720p"
	}
	playURL := fmt.Sprintf("https://aweme.snssdk.com/aweme/v1/play/?video_id=%s&ratio=%s", videoURI, ratio)

	req, err := http.NewRequest("GET", playURL, nil)
	if err != nil {
		return "", 0
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Linux; Android 10)")

	resp, err := p.noRedirectClient.Do(req)
	if err != nil {
		return "", 0
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusFound || resp.StatusCode == http.StatusMovedPermanently {
		loc := resp.Header.Get("Location")
		if loc != "" {
			return loc, 0
		}
	}

	// 降级使用 Request URL
	finalURL := resp.Request.URL.String()
	var sizeMB float64
	if resp.ContentLength > 0 {
		sizeMB = math.Round(float64(resp.ContentLength)/1024/1024*100) / 100
	}
	return finalURL, sizeMB
}

// 抖音 JSON 反序列化结构体
type douyinFeedResponse struct {
	AwemeList []douyinAwemeDetail `json:"aweme_list"`
}

type douyinAwemeDetail struct {
	AwemeID string       `json:"aweme_id"`
	Desc    string       `json:"desc"`
	Author  douyinAuthor `json:"author"`
	Video   douyinVideo  `json:"video"`
}

type douyinAuthor struct {
	Nickname    string      `json:"nickname"`
	AvatarThumb douyinImage `json:"avatar_thumb"`
}

type douyinImage struct {
	URLList []string `json:"url_list"`
}

type douyinVideo struct {
	Duration int             `json:"duration"`
	Cover    douyinImage     `json:"cover"`
	PlayAddr douyinPlayAddr  `json:"play_addr"`
	BitRate  []douyinBitrate `json:"bit_rate"`
}

type douyinPlayAddr struct {
	URI      string   `json:"uri"`
	URLList  []string `json:"url_list"`
	DataSize int64    `json:"data_size"`
	Width    int      `json:"width"`
	Height   int      `json:"height"`
}

type douyinBitrate struct {
	GearName string         `json:"gear_name"`
	BitRate  int            `json:"bit_rate"`
	IsH265   int            `json:"is_h265"`
	PlayAddr douyinPlayAddr `json:"play_addr"`
}
