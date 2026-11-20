package api

import (
	"encoding/json"
	"net/http"
	"vrc-video-core/parsers"
	"vrc-video-core/proxy"
)

type APIHandler struct {
	parser *parsers.UnifiedParser
	proxy  *proxy.ProxyServer
}

func NewAPIHandler(p *parsers.UnifiedParser, s *proxy.ProxyServer) *APIHandler {
	return &APIHandler{
		parser: p,
		proxy:  s,
	}
}

type ParseRequest struct {
	Text         string `json:"text"`
	PlatformHint string `json:"platform_hint"`
}

type APIResponse struct {
	Code int         `json:"code"` // 0 为成功，非 0 为失败
	Msg  string      `json:"msg"`
	Data interface{} `json:"data,omitempty"`
}

func (h *APIHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/parse", h.handleParse)
	mux.HandleFunc("/api/status", h.handleStatus)
	mux.HandleFunc("/api/ping", h.handlePing)
}

func (h *APIHandler) handleParse(w http.ResponseWriter, r *http.Request) {
	setCORS(w)
	if r.Method == "OPTIONS" {
		w.WriteHeader(http.StatusOK)
		return
	}
	if r.Method != "POST" {
		jsonResp(w, http.StatusMethodNotAllowed, 405, "Method Not Allowed", nil)
		return
	}

	var req ParseRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		jsonResp(w, http.StatusBadRequest, 400, "无效的 JSON 请求体", nil)
		return
	}

	if req.Text == "" {
		jsonResp(w, http.StatusBadRequest, 400, "解析文本内容不能为空", nil)
		return
	}

	info, err := h.parser.Parse(req.Text, req.PlatformHint)
	if err != nil {
		jsonResp(w, http.StatusOK, 1, err.Error(), nil)
		return
	}

	jsonResp(w, http.StatusOK, 0, "ok", info)
}

func (h *APIHandler) handleStatus(w http.ResponseWriter, r *http.Request) {
	setCORS(w)
	statusData := map[string]interface{}{
		"status":     "running",
		"proxy_port": h.proxy.Port,
		"local_ips":  h.proxy.GetLocalIPs(),
	}
	jsonResp(w, http.StatusOK, 0, "ok", statusData)
}

func (h *APIHandler) handlePing(w http.ResponseWriter, r *http.Request) {
	setCORS(w)
	jsonResp(w, http.StatusOK, 0, "pong", nil)
}

func setCORS(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
}

func jsonResp(w http.ResponseWriter, httpCode, code int, msg string, data interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(httpCode)
	resp := APIResponse{
		Code: code,
		Msg:  msg,
		Data: data,
	}
	json.NewEncoder(w).Encode(resp)
}
