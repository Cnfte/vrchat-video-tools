package parsers

import (
	"errors"
	"strings"
	"sync"
)

type UnifiedParser struct {
	bilibili *BilibiliParser
	douyin   *DouyinParser
	kuaishou *KuaishouParser
}

func NewUnifiedParser() *UnifiedParser {
	return &UnifiedParser{
		bilibili: NewBilibiliParser(),
		douyin:   NewDouyinParser(),
		kuaishou: NewKuaishouParser(),
	}
}

// Parse 智能路由并解析
func (u *UnifiedParser) Parse(inputText string, platformHint string) (*VideoInfo, error) {
	cleanText := strings.TrimSpace(inputText)
	if cleanText == "" {
		return nil, errors.New("输入内容不能为空")
	}

	hint := strings.ToLower(strings.TrimSpace(platformHint))
	detected := DetectPlatform(cleanText)

	targetPlatform := detected
	if hint != "" && hint != "auto" {
		targetPlatform = hint
	}

	switch targetPlatform {
	case "bilibili":
		return u.bilibili.Parse(cleanText)
	case "douyin":
		return u.douyin.Parse(cleanText)
	case "kuaishou":
		return u.kuaishou.Parse(cleanText)
	default:
		// 当平台无法直接由特征码推断时，并发同时尝试三个解析器，最快成功者立即返回 (杜绝几十秒串行超时)
		resChan := make(chan *VideoInfo, 3)
		var wg sync.WaitGroup

		wg.Add(3)
		go func() {
			defer wg.Done()
			if info, err := u.bilibili.Parse(cleanText); err == nil && info != nil {
				select {
				case resChan <- info:
				default:
				}
			}
		}()
		go func() {
			defer wg.Done()
			if info, err := u.douyin.Parse(cleanText); err == nil && info != nil {
				select {
				case resChan <- info:
				default:
				}
			}
		}()
		go func() {
			defer wg.Done()
			if info, err := u.kuaishou.Parse(cleanText); err == nil && info != nil {
				select {
				case resChan <- info:
				default:
				}
			}
		}()

		doneChan := make(chan struct{})
		go func() {
			wg.Wait()
			close(doneChan)
		}()

		select {
		case firstSuccess := <-resChan:
			return firstSuccess, nil
		case <-doneChan:
			select {
			case firstSuccess := <-resChan:
				return firstSuccess, nil
			default:
				return nil, errors.New("未能识别视频所属平台，请确认链接是否完整正确")
			}
		}
	}
}
