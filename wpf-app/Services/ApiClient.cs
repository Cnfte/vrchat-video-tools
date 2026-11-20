using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using VRCVideoTools.App.Models;

namespace VRCVideoTools.App.Services
{
    public class ApiClient
    {
        private readonly HttpClient _http;
        public int Port { get; private set; }

        public ApiClient(int port = 9527)
        {
            Port = port;
            var handler = new SocketsHttpHandler
            {
                UseProxy = false,
                Proxy = null,
                PooledConnectionLifetime = TimeSpan.FromMinutes(10),
                EnableMultipleHttp2Connections = true
            };
            _http = new HttpClient(handler)
            {
                BaseAddress = new Uri($"http://127.0.0.1:{port}/"),
                Timeout = TimeSpan.FromSeconds(15)
            };
        }

        public async Task<bool> PingAsync()
        {
            try
            {
                using var cts = new System.Threading.CancellationTokenSource(TimeSpan.FromMilliseconds(450));
                var resp = await _http.GetAsync("api/ping", cts.Token);
                return resp.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        public async Task<EngineStatus?> GetStatusAsync()
        {
            try
            {
                using var cts = new System.Threading.CancellationTokenSource(TimeSpan.FromSeconds(2));
                var resp = await _http.GetAsync("api/status", cts.Token);
                if (resp.IsSuccessStatusCode)
                {
                    var json = await resp.Content.ReadAsStringAsync(cts.Token);
                    var apiResp = JsonSerializer.Deserialize<ApiResponse<EngineStatus>>(json);
                    return apiResp?.Data;
                }
            }
            catch
            {
                // ignored
            }
            return null;
        }

        public async Task<VideoInfo> ParseAsync(string text, string platformHint = "auto")
        {
            var reqObj = new { text = text, platform_hint = platformHint };
            var content = new StringContent(JsonSerializer.Serialize(reqObj), Encoding.UTF8, "application/json");

            var resp = await _http.PostAsync("api/parse", content);
            var json = await resp.Content.ReadAsStringAsync();

            if (!resp.IsSuccessStatusCode)
            {
                throw new Exception($"HTTP 请求失败: {resp.StatusCode}");
            }

            var apiResp = JsonSerializer.Deserialize<ApiResponse<VideoInfo>>(json);
            if (apiResp == null)
            {
                throw new Exception("解析结果数据为空");
            }
            if (apiResp.Code != 0)
            {
                throw new Exception(apiResp.Msg);
            }
            if (apiResp.Data == null)
            {
                throw new Exception("视频数据为空");
            }
            return apiResp.Data;
        }

        public string GetRelayUrl(string targetUrl, string platform, string host = "")
        {
            if (string.IsNullOrEmpty(host)) host = "127.0.0.1";
            var encoded = Uri.EscapeDataString(targetUrl);
            return $"http://{host}:{Port}/stream.mp4?url={encoded}&platform={platform}";
        }

        public string GetPlayerUrl(string targetUrl, string platform)
        {
            var encoded = Uri.EscapeDataString(targetUrl);
            return $"http://127.0.0.1:{Port}/player?url={encoded}&platform={platform}";
        }
    }
}
