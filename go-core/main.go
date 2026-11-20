package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"
	"vrc-video-core/api"
	"vrc-video-core/parsers"
	"vrc-video-core/proxy"
)

func main() {
	port := flag.Int("port", 9527, "服务监听端口 (流媒体代理与 API)")
	parseUrl := flag.String("parse", "", "测试解析指定 URL 并以 JSON 输出")
	flag.Parse()

	unifiedParser := parsers.NewUnifiedParser()

	// 如果指定了 -parse 参数，执行单次命令行解析
	if *parseUrl != "" {
		info, err := unifiedParser.Parse(*parseUrl, "auto")
		if err != nil {
			log.Fatalf("解析失败: %v", err)
		}
		data, _ := json.MarshalIndent(info, "", "  ")
		fmt.Println(string(data))
		return
	}

	log.Println("============================================================")
	log.Println("VRC-VideoTools Go 流媒体内核正在初始化...")
	log.Printf("监听端口: %d", *port)
	log.Println("============================================================")

	proxyServer := proxy.NewProxyServer(*port)
	apiHandler := api.NewAPIHandler(unifiedParser, proxyServer)

	// 注册 REST API 路由到同一个 Mux
	apiHandler.RegisterRoutes(proxyServer.Mux)

	if err := proxyServer.Start(); err != nil {
		log.Fatalf("启动服务失败: %v", err)
	}

	log.Printf("VRC-VideoTools Go 内核服务已完全就绪")
	log.Printf("  - API 状态: http://127.0.0.1:%d/api/status", *port)
	log.Printf("  - 解析接口: http://127.0.0.1:%d/api/parse", *port)
	log.Printf("  - 媒体中继: http://127.0.0.1:%d/stream.mp4", *port)

	// 监听中断退出信号
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	<-sigChan

	log.Println("正在停止服务...")
	proxyServer.Stop()
	time.Sleep(200 * time.Millisecond)
	log.Println("Go 内核服务已完全停止。")
}
