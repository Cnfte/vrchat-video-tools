package parsers

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"regexp"
	"strings"
	"time"
)

const (
	kuaishouUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

var (
	kuaishouPhotoIDRegexes = []*regexp.Regexp{
		regexp.MustCompile(`/short-video/([a-zA-Z0-9_-]+)`),
		regexp.MustCompile(`/photo/([a-zA-Z0-9_-]+)`),
		regexp.MustCompile(`photoId=([a-zA-Z0-9_-]+)`),
	}
)

type KuaishouParser struct {
	client *http.Client
}

func NewKuaishouParser() *KuaishouParser {
	jar, _ := cookiejar.New(nil)
	return &KuaishouParser{
		client: &http.Client{
			Jar:     jar,
			Timeout: 15 * time.Second,
		},
	}
}

// ExtractPhotoID 提取快手作品 ID
func (p *KuaishouParser) ExtractPhotoID(inputText string) (string, error) {
	rawURL := ExtractURL(inputText)
	if rawURL == "" {
		rawURL = strings.TrimSpace(inputText)
	}

	target := rawURL
	if strings.HasPrefix(target, "http") {
		// 1. 探测 302 重定向
		noRedirectClient := &http.Client{
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
			Timeout: 10 * time.Second,
		}
		req, err := http.NewRequest("GET", target, nil)
		if err == nil {
			req.Header.Set("User-Agent", kuaishouUA)
			resp, err := noRedirectClient.Do(req)
			if err == nil {
				resp.Body.Close()
				loc := resp.Header.Get("Location")
				if loc != "" {
					for _, reg := range kuaishouPhotoIDRegexes {
						if m := reg.FindStringSubmatch(loc); len(m) > 1 {
							return m[1], nil
						}
					}
					target = loc
				}
			}
		}

		// 2. 追踪完整跳转
		reqFull, err := http.NewRequest("GET", target, nil)
		if err == nil {
			reqFull.Header.Set("User-Agent", kuaishouUA)
			respFull, err := p.client.Do(reqFull)
			if err == nil {
				respFull.Body.Close()
				finalURL := respFull.Request.URL.String()
				for _, reg := range kuaishouPhotoIDRegexes {
					if m := reg.FindStringSubmatch(finalURL); len(m) > 1 {
						return m[1], nil
					}
				}
			}
		}
	}

	for _, reg := range kuaishouPhotoIDRegexes {
		if m := reg.FindStringSubmatch(target); len(m) > 1 {
			return m[1], nil
		}
	}

	return "", errors.New("未能提取到有效的快手视频链接或作品 ID")
}

// Parse 执行快手视频解析
func (p *KuaishouParser) Parse(inputText string) (*VideoInfo, error) {
	photoID, err := p.ExtractPhotoID(inputText)
	if err != nil {
		return nil, err
	}

	// 初始化会话凭据
	p.initCookies()

	graphqlURL := "https://www.kuaishou.com/graphql"
	query := `query visionVideoDetail($photoId: String, $type: String, $page: String, $webPageArea: String) {
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
	}`

	payload := map[string]interface{}{
		"operationName": "visionVideoDetail",
		"variables": map[string]interface{}{
			"photoId":     photoID,
			"page":        "detail",
			"webPageArea": "detail",
		},
		"query": query,
	}

	payloadBytes, _ := json.Marshal(payload)
	req, err := http.NewRequest("POST", graphqlURL, bytes.NewBuffer(payloadBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", kuaishouUA)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Referer", fmt.Sprintf("https://www.kuaishou.com/short-video/%s", photoID))

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("请求快手 GraphQL 接口异常: %v", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var res ksGraphQLResponse
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, err
	}

	vDetail := res.Data.VisionVideoDetail
	photo := vDetail.Photo
	if photo.PhotoURL == "" && len(photo.Manifest.AdaptationSet) == 0 {
		return nil, errors.New("快手未返回可用视频直链，可能为私密作品或作品已删除")
	}

	title := strings.TrimSpace(photo.Caption)
	if title == "" {
		title = "快手短视频"
	}
	authorName := vDetail.Author.Name
	if authorName == "" {
		authorName = "快手创作者"
	}
	authorAvatar := vDetail.Author.HeaderURL
	durationSec := photo.Duration / 1000
	coverURL := photo.CoverURL

	var qualities []VideoQuality
	// 1. 优先提取多码率流 (过滤 representation)
	for _, adapt := range photo.Manifest.AdaptationSet {
		for _, rep := range adapt.Representation {
			if rep.URL != "" {
				lbl := rep.QualityLabel
				if lbl == "" {
					lbl = fmt.Sprintf("%dP", rep.Height)
				}
				qualities = append(qualities, VideoQuality{
					Label: fmt.Sprintf("%s (官方原生流)", lbl),
					URL:   rep.URL,
				})
			}
		}
	}

	// 2. 兜底 photoUrl
	if photo.PhotoURL != "" {
		qualities = append(qualities, VideoQuality{
			Label: "无水印高清 (主干线路)",
			URL:   photo.PhotoURL,
		})
	}

	if len(qualities) == 0 {
		return nil, errors.New("未能解析到快手视频播放流")
	}

	best := qualities[0]
	return &VideoInfo{
		Platform:     "kuaishou",
		PlatformName: "快手",
		VideoID:      photoID,
		Title:        title,
		Author:       authorName,
		AuthorAvatar: authorAvatar,
		DurationSec:  durationSec,
		DurationStr:  FormatDuration(durationSec),
		CoverURL:     coverURL,
		PlayURL:      best.URL,
		Quality:      best.Label,
		Qualities:    qualities,
	}, nil
}

func (p *KuaishouParser) initCookies() {
	req, _ := http.NewRequest("GET", "https://www.kuaishou.com/", nil)
	if req != nil {
		req.Header.Set("User-Agent", kuaishouUA)
		resp, err := p.client.Do(req)
		if err == nil {
			resp.Body.Close()
		}
	}
}

type ksGraphQLResponse struct {
	Data struct {
		VisionVideoDetail struct {
			Status int      `json:"status"`
			Author ksAuthor `json:"author"`
			Photo  ksPhoto  `json:"photo"`
		} `json:"visionVideoDetail"`
	} `json:"data"`
}

type ksAuthor struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	HeaderURL string `json:"headerUrl"`
}

type ksPhoto struct {
	ID       string     `json:"id"`
	Duration int        `json:"duration"`
	Caption  string     `json:"caption"`
	CoverURL string     `json:"coverUrl"`
	PhotoURL string     `json:"photoUrl"`
	Manifest ksManifest `json:"manifest"`
}

type ksManifest struct {
	AdaptationSet []struct {
		Representation []struct {
			ID           int    `json:"id"`
			URL          string `json:"url"`
			QualityLabel string `json:"qualityLabel"`
			Height       int    `json:"height"`
		} `json:"representation"`
	} `json:"adaptationSet"`
}
