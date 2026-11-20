package proxy

import (
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

type ProxyServer struct {
	Port       int
	Mux        *http.ServeMux
	server     *http.Server
	client     *http.Client
	localIPs   []string
	activeConn int64
	mu         sync.Mutex
}

func NewProxyServer(port int) *ProxyServer {
	mux := http.NewServeMux()
	s := &ProxyServer{
		Port: port,
		Mux:  mux,
		client: &http.Client{
			Timeout: 0, // 流媒体长连接不设整体超时
		},
		localIPs: detectLocalIPs(),
	}

	mux.HandleFunc("/stream", s.handleStream)
	mux.HandleFunc("/stream.mp4", s.handleStream)
	mux.HandleFunc("/player", s.handlePlayer)
	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("pong"))
	})

	return s
}

// Start 启动流媒体代理服务
func (s *ProxyServer) Start() error {
	s.server = &http.Server{
		Addr:         fmt.Sprintf("0.0.0.0:%d", s.Port),
		Handler:      s.Mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 0, // 流媒体持久推流
	}

	ln, err := net.Listen("tcp", s.server.Addr)
	if err != nil {
		return err
	}

	go func() {
		if err := s.server.Serve(ln); err != nil && err != http.ErrServerClosed {
			log.Printf("[ProxyServer] 异常退出: %v", err)
		}
	}()

	log.Printf("[ProxyServer] VRChat 流媒体代理中继已成功监听端口: %d", s.Port)
	return nil
}

// Stop 停止流媒体代理服务
func (s *ProxyServer) Stop() error {
	if s.server != nil {
		return s.server.Close()
	}
	return nil
}

// GetLocalIPs 获取本机所有局域网 IPv4
func (s *ProxyServer) GetLocalIPs() []string {
	return s.localIPs
}

// GetStreamURL 生成 VRChat 全员播放流地址
func (s *ProxyServer) GetStreamURL(targetURL, platform string, host string) string {
	if host == "" {
		if len(s.localIPs) > 0 {
			host = s.localIPs[0]
		} else {
			host = "127.0.0.1"
		}
	}
	return fmt.Sprintf("http://%s:%d/stream.mp4?url=%s&platform=%s", host, s.Port, strings.ReplaceAll(targetURL, "&", "%26"), platform)
}

func (s *ProxyServer) handleStream(w http.ResponseWriter, r *http.Request) {
	// CORS 响应头，允许 VRChat 与 Webview 跨域
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Range, Accept, Origin, Content-Type")
	w.Header().Set("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")

	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}

	targetURL := r.URL.Query().Get("url")
	platform := r.URL.Query().Get("platform")

	if targetURL == "" {
		http.Error(w, "Missing 'url' parameter", http.StatusBadRequest)
		return
	}

	upstreamReq, err := http.NewRequest("GET", targetURL, nil)
	if err != nil {
		http.Error(w, "Invalid upstream URL", http.StatusBadRequest)
		return
	}

	// 注入对应平台的防盗链 Referer 与 User-Agent
	upstreamReq.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
	switch {
	case platform == "bilibili" || strings.Contains(targetURL, "bilivideo.com") || strings.Contains(targetURL, "bilibili.com"):
		upstreamReq.Header.Set("Referer", "https://www.bilibili.com/")
	case platform == "douyin" || strings.Contains(targetURL, "douyinvod.com") || strings.Contains(targetURL, "douyin.com"):
		upstreamReq.Header.Set("Referer", "https://www.douyin.com/")
	case platform == "kuaishou" || strings.Contains(targetURL, "kwaicdn.com") || strings.Contains(targetURL, "kuaishou.com"):
		upstreamReq.Header.Set("Referer", "https://www.kuaishou.com/")
	}

	// 转发客户端 Range 头 (支持 VRChat AVPro 播放器拖动进度条)
	if clientRange := r.Header.Get("Range"); clientRange != "" {
		upstreamReq.Header.Set("Range", clientRange)
	}

	resp, err := s.client.Do(upstreamReq)
	if err != nil {
		http.Error(w, fmt.Sprintf("Upstream error: %v", err), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	// 转发关键响应头
	for _, h := range []string{"Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag"} {
		if val := resp.Header.Get(h); val != "" {
			w.Header().Set(h, val)
		}
	}
	if w.Header().Get("Content-Type") == "" {
		w.Header().Set("Content-Type", "video/mp4")
	}
	w.Header().Set("Accept-Ranges", "bytes")

	w.WriteHeader(resp.StatusCode)

	// 高吞吐零拷贝流式转发
	buf := make([]byte, 64*1024)
	io.CopyBuffer(w, resp.Body, buf)
}

func (s *ProxyServer) handlePlayer(w http.ResponseWriter, r *http.Request) {
	targetURL := r.URL.Query().Get("url")
	platform := r.URL.Query().Get("platform")

	streamSrc := fmt.Sprintf("/stream.mp4?url=%s&platform=%s", strings.ReplaceAll(targetURL, "&", "%26"), platform)

	html := fmt.Sprintf(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>VRC-VideoTools 流媒体预览验证</title>
    <style>
        body { margin: 0; background: #0f111a; color: #fff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; }
        .card { width: 90%%; max-width: 800px; background: #1a1b26; padding: 24px; border-radius: 12px; border: 1px solid #2f334d; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
        video { width: 100%%; max-height: 480px; border-radius: 8px; background: #000; outline: none; }
        h2 { margin-top: 0; color: #7aa2f7; }
        p { color: #a9b1d6; font-size: 14px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>VRC-VideoTools 视频流代理播放测试</h2>
        <video controls autoplay preload="auto">
            <source src="%s" type="video/mp4">
            您的浏览器不支持 HTML5 视频播放
        </video>
        <p>当前视频正通过 VRC-VideoTools 高性能 Go 内核流式传输 (已自动注入防盗链请求头)。<br>此页面可播放则说明 VRChat 播放器完全可用！</p>
    </div>
</body>
</html>`, streamSrc)

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(html))
}

func detectLocalIPs() []string {
	var ips []string
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return []string{"127.0.0.1"}
	}
	for _, addr := range addrs {
		if ipNet, ok := addr.(*net.IPNet); ok && !ipNet.IP.IsLoopback() {
			if ipNet.IP.To4() != nil {
				ips = append(ips, ipNet.IP.String())
			}
		}
	}
	if len(ips) == 0 {
		ips = append(ips, "127.0.0.1")
	}
	return ips
}
