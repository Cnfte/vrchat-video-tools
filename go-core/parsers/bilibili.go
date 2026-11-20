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
	"strconv"
	"strings"
	"time"
)

const (
	bilibiliUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

var (
	bvidRegex   = regexp.MustCompile(`(?i)\b(BV[a-zA-Z0-9]{10})\b`)
	avidRegex   = regexp.MustCompile(`(?i)\bav(\d+)\b`)
	uposReplace = regexp.MustCompile(`https?://[^/]+/`)
)

type BilibiliParser struct {
	client           *http.Client
	noRedirectClient *http.Client
}

func NewBilibiliParser() *BilibiliParser {
	transport := &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 20,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression:  false,
		ForceAttemptHTTP2:   true,
	}
	return &BilibiliParser{
		client: &http.Client{
			Transport: transport,
			Timeout:   10 * time.Second,
		},
		noRedirectClient: &http.Client{
			Transport: transport,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
			Timeout: 4 * time.Second,
		},
	}
}

// ExtractID 从输入中提取 BVID 或 AVID 以及分 P
func (p *BilibiliParser) ExtractID(inputText string) (bvid string, avid string, pageNum int) {
	pageNum = 1
	rawURL := ExtractURL(inputText)

	// 若为 b23.tv 短链，不跟随跳转直接捕获 302 Location (毫秒级提取真实 BV 号)
	if strings.Contains(rawURL, "b23.tv") {
		if req, err := http.NewRequest("GET", rawURL, nil); err == nil {
			req.Header.Set("User-Agent", bilibiliUA)
			if resp, err := p.noRedirectClient.Do(req); err == nil {
				resp.Body.Close()
				if loc := resp.Header.Get("Location"); loc != "" {
					rawURL = loc
					inputText = loc
				}
			}
		}
	}

	if rawURL != "" {
		if u, err := url.Parse(rawURL); err == nil {
			if pStr := u.Query().Get("p"); pStr != "" {
				if parsedP, err := strconv.Atoi(pStr); err == nil && parsedP > 0 {
					pageNum = parsedP
				}
			}
		}
	}

	if m := bvidRegex.FindStringSubmatch(inputText); len(m) > 1 {
		bvid = m[1]
		return
	}
	if m := avidRegex.FindStringSubmatch(inputText); len(m) > 1 {
		avid = m[1]
		return
	}
	return
}

// Parse 执行 B站 视频解析
func (p *BilibiliParser) Parse(inputText string) (*VideoInfo, error) {
	bvid, avid, pageNum := p.ExtractID(inputText)
	if bvid == "" && avid == "" {
		return nil, errors.New("未能识别到有效的 B站 视频链接或 BV/AV 号")
	}

	// 1. 获取视频基本元数据 (cid, 标题, 作者等) 优先走免 412 WAF 的 wbi/view 接口
	viewURL := "https://api.bilibili.com/x/web-interface/wbi/view"
	params := url.Values{}
	if bvid != "" {
		params.Set("bvid", bvid)
	} else {
		params.Set("aid", avid)
	}

	req, err := http.NewRequest("GET", viewURL+"?"+params.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", bilibiliUA)
	req.Header.Set("Referer", "https://www.bilibili.com/")

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("请求 B站 视频信息失败: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var viewRes biliViewResponse
	if err := json.Unmarshal(body, &viewRes); err != nil {
		return nil, err
	}
	if viewRes.Code != 0 {
		return nil, fmt.Errorf("B站接口返回错误: [%d] %s", viewRes.Code, viewRes.Message)
	}

	vdata := viewRes.Data
	resolvedBvid := vdata.Bvid
	if resolvedBvid == "" {
		resolvedBvid = bvid
	}
	title := vdata.Title
	authorName := vdata.Owner.Name
	authorAvatar := vdata.Owner.Face
	coverURL := vdata.Pic
	totalDuration := vdata.Duration

	// 处理分 P
	var targetCID int64
	targetDuration := totalDuration
	if len(vdata.Pages) > 0 && pageNum <= len(vdata.Pages) {
		page := vdata.Pages[pageNum-1]
		targetCID = page.CID
		if len(vdata.Pages) > 1 && page.Part != "" {
			title = fmt.Sprintf("%s (P%d %s)", title, pageNum, page.Part)
		}
		if page.Duration > 0 {
			targetDuration = page.Duration
		}
	} else {
		targetCID = vdata.CID
	}

	if targetCID == 0 {
		return nil, errors.New("未能获取到视频流核心 CID")
	}

	// 2. 请求播放直链 (使用 platform=html5 注入免防盗链令牌)
	playURLAPI := "https://api.bilibili.com/x/player/playurl"
	playParams := url.Values{}
	playParams.Set("bvid", resolvedBvid)
	playParams.Set("cid", strconv.FormatInt(targetCID, 10))
	playParams.Set("qn", "80") // 1080P/720P
	playParams.Set("fnval", "1") // 纯 MP4 混流模式 (音视频合一)
	playParams.Set("fnver", "0")
	playParams.Set("fourk", "1")
	playParams.Set("platform", "html5")
	playParams.Set("high_quality", "1")
	playParams.Set("build", "7330300")

	playReq, err := http.NewRequest("GET", playURLAPI+"?"+playParams.Encode(), nil)
	if err != nil {
		return nil, err
	}
	playReq.Header.Set("User-Agent", bilibiliUA)
	playReq.Header.Set("Referer", "https://www.bilibili.com/")

	playResp, err := p.client.Do(playReq)
	if err != nil {
		return nil, fmt.Errorf("请求播放直链异常: %v", err)
	}
	defer playResp.Body.Close()

	playBody, err := io.ReadAll(playResp.Body)
	if err != nil {
		return nil, err
	}

	var playRes biliPlayurlResponse
	if err := json.Unmarshal(playBody, &playRes); err != nil {
		return nil, err
	}
	if playRes.Code != 0 {
		return nil, fmt.Errorf("B站播放地址错误 [%d]: %s", playRes.Code, playRes.Message)
	}

	if len(playRes.Data.DURL) == 0 {
		return nil, errors.New("未能解析出可播放的 MP4 视频直链地址")
	}

	mainDURL := playRes.Data.DURL[0]
	rawPlayURL := mainDURL.URL
	sizeMB := math.Round(float64(mainDURL.Size)/1024/1024*100) / 100

	qnMap := map[int]string{
		120: "4K 超高清",
		116: "1080P 60帧",
		80:  "1080P 高清 (免Referer)",
		64:  "720P 高清 (免Referer)",
		32:  "480P 清晰",
		16:  "360P 流畅",
	}
	qualityLabel := qnMap[playRes.Data.Quality]
	if qualityLabel == "" {
		qualityLabel = fmt.Sprintf("高清 (%dP)", playRes.Data.Quality)
	}

	// 核心：构建中文吧 / 中文咖啡厅及 VRChat 房间专用 mirrorcos 免防盗链直链 (注入鉴权参数)
	mirrorcosURL := uposReplace.ReplaceAllString(rawPlayURL, "https://upos-sz-mirrorcos.bilivideo.com/")
	mirrorcosURL = strings.Replace(mirrorcosURL, "build=0", "build=7330300", 1)
	mirrorcosURL = strings.Replace(mirrorcosURL, "orderid=0,1", "orderid=0,3", 1)

	var qualities []VideoQuality
	// 1. 第一选项（默认核心）：中文吧 / 中文咖啡厅专用 mirrorcos 节点 (已穿透防盗链)
	qualities = append(qualities, VideoQuality{
		Label:  fmt.Sprintf("%s (mirrorcos 节点 · 中文吧/咖啡厅直连 · 推荐)", qualityLabel),
		URL:    mirrorcosURL,
		SizeMB: sizeMB,
	})

	best := qualities[0]
	return &VideoInfo{
		Platform:     "bilibili",
		PlatformName: "哔哩哔哩",
		VideoID:      resolvedBvid,
		Title:        title,
		Author:       authorName,
		AuthorAvatar: authorAvatar,
		DurationSec:  targetDuration,
		DurationStr:  FormatDuration(targetDuration),
		CoverURL:     coverURL,
		PlayURL:      best.URL,
		SizeMB:       best.SizeMB,
		Quality:      best.Label,
		Qualities:    qualities,
	}, nil
}

// B站 JSON 响应结构体
type biliViewResponse struct {
	Code    int          `json:"code"`
	Message string       `json:"message"`
	Data    biliViewData `json:"data"`
}

type biliViewData struct {
	Bvid     string     `json:"bvid"`
	Aid      int64      `json:"aid"`
	Title    string     `json:"title"`
	Pic      string     `json:"pic"`
	Duration int        `json:"duration"`
	CID      int64      `json:"cid"`
	Owner    biliOwner  `json:"owner"`
	Pages    []biliPage `json:"pages"`
}

type biliOwner struct {
	Name string `json:"name"`
	Face string `json:"face"`
}

type biliPage struct {
	CID      int64  `json:"cid"`
	Page     int    `json:"page"`
	Part     string `json:"part"`
	Duration int    `json:"duration"`
}

type biliPlayurlResponse struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    biliPlayurlData `json:"data"`
}

type biliPlayurlData struct {
	Quality int           `json:"quality"`
	DURL    []biliDURLItem `json:"durl"`
}

type biliDURLItem struct {
	URL       string   `json:"url"`
	Size      int64    `json:"size"`
	BackupURL []string `json:"backup_url"`
}
