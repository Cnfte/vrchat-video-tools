using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace VRCVideoTools.App.Models
{
    public class VideoQuality
    {
        [JsonPropertyName("label")]
        public string Label { get; set; } = string.Empty;

        [JsonPropertyName("url")]
        public string Url { get; set; } = string.Empty;

        [JsonPropertyName("size_mb")]
        public double SizeMB { get; set; }

        public string DisplayText => SizeMB > 0 ? $"{Label} ({SizeMB:F2} MB)" : Label;
    }

    public class VideoInfo
    {
        [JsonPropertyName("platform")]
        public string Platform { get; set; } = string.Empty;

        [JsonPropertyName("platform_name")]
        public string PlatformName { get; set; } = string.Empty;

        [JsonPropertyName("video_id")]
        public string VideoId { get; set; } = string.Empty;

        [JsonPropertyName("title")]
        public string Title { get; set; } = string.Empty;

        [JsonPropertyName("author")]
        public string Author { get; set; } = string.Empty;

        [JsonPropertyName("author_avatar")]
        public string AuthorAvatar { get; set; } = string.Empty;

        [JsonPropertyName("duration_sec")]
        public int DurationSec { get; set; }

        [JsonPropertyName("duration_str")]
        public string DurationStr { get; set; } = string.Empty;

        [JsonPropertyName("cover_url")]
        public string CoverUrl { get; set; } = string.Empty;

        [JsonPropertyName("play_url")]
        public string PlayUrl { get; set; } = string.Empty;

        [JsonPropertyName("size_mb")]
        public double SizeMB { get; set; }

        [JsonPropertyName("quality")]
        public string Quality { get; set; } = string.Empty;

        [JsonPropertyName("qualities")]
        public List<VideoQuality> Qualities { get; set; } = new();
    }

    public class ApiResponse<T>
    {
        [JsonPropertyName("code")]
        public int Code { get; set; }

        [JsonPropertyName("msg")]
        public string Msg { get; set; } = string.Empty;

        [JsonPropertyName("data")]
        public T? Data { get; set; }
    }

    public class EngineStatus
    {
        [JsonPropertyName("status")]
        public string Status { get; set; } = string.Empty;

        [JsonPropertyName("proxy_port")]
        public int ProxyPort { get; set; }

        [JsonPropertyName("local_ips")]
        public List<string> LocalIPs { get; set; } = new();
    }
}
