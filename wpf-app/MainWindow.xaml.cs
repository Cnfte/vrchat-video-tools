using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using VRCVideoTools.App.Models;
using VRCVideoTools.App.Services;
using Wpf.Ui.Controls;

namespace VRCVideoTools.App
{
    public enum NoticeLevel
    {
        Info,
        Success,
        Warning,
        Error
    }

    public partial class MainWindow : Window
    {
        private readonly ApiClient _apiClient;
        private readonly CoreProcessManager _processManager;
        private VideoInfo? _currentInfo;
        private readonly Dictionary<System.Windows.Controls.Button, int> _copyAnimTokens = new();

        public MainWindow()
        {
            InitializeComponent();
            _apiClient = new ApiClient(9527);
            _processManager = new CoreProcessManager(9527);

            MaxHeight = SystemParameters.WorkArea.Height + 14;
            Loaded += MainWindow_Loaded;
            Closing += MainWindow_Closing;
            StateChanged += MainWindow_StateChanged;
        }

        private void MainWindow_StateChanged(object? sender, EventArgs e)
        {
            bool maximized = WindowState == WindowState.Maximized;
            RootMarginGrid.Margin = maximized ? new Thickness(0) : new Thickness(16);
            WindowShellBorder.CornerRadius = maximized ? new CornerRadius(0) : new CornerRadius(18);
            WindowShellBorder.BorderThickness = maximized ? new Thickness(0) : new Thickness(1);
        }

        private void HeaderBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ClickCount == 2)
            {
                ToggleMaximize();
                return;
            }
            if (e.ButtonState == MouseButtonState.Pressed)
            {
                DragMove();
            }
        }

        private void MinimizeBtn_Click(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

        private void MaximizeBtn_Click(object sender, RoutedEventArgs e) => ToggleMaximize();

        private void ToggleMaximize()
        {
            WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
        }

        private void CloseBtn_Click(object sender, RoutedEventArgs e) => Close();

        #region Custom Frameless Edge Resize Handlers
        private void ResizeLeft_DragDelta(object sender, DragDeltaEventArgs e)
        {
            if (WindowState == WindowState.Maximized) return;
            double newWidth = Width - e.HorizontalChange;
            if (newWidth >= MinWidth)
            {
                Left += e.HorizontalChange;
                Width = newWidth;
            }
        }

        private void ResizeRight_DragDelta(object sender, DragDeltaEventArgs e)
        {
            if (WindowState == WindowState.Maximized) return;
            double newWidth = Width + e.HorizontalChange;
            if (newWidth >= MinWidth) Width = newWidth;
        }

        private void ResizeTop_DragDelta(object sender, DragDeltaEventArgs e)
        {
            if (WindowState == WindowState.Maximized) return;
            double newHeight = Height - e.VerticalChange;
            if (newHeight >= MinHeight)
            {
                Top += e.VerticalChange;
                Height = newHeight;
            }
        }

        private void ResizeBottom_DragDelta(object sender, DragDeltaEventArgs e)
        {
            if (WindowState == WindowState.Maximized) return;
            double newHeight = Height + e.VerticalChange;
            if (newHeight >= MinHeight) Height = newHeight;
        }

        private void ResizeBottomRight_DragDelta(object sender, DragDeltaEventArgs e)
        {
            ResizeRight_DragDelta(sender, e);
            ResizeBottom_DragDelta(sender, e);
        }
        #endregion

        private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
        {
            Log("正在初始化流媒体引擎与网络探测...");
            bool ok = await _processManager.EnsureRunningAsync(_apiClient);
            if (ok)
            {
                var greenBrush = new SolidColorBrush(Color.FromRgb(136, 201, 157));
                CoreStatusBadge.Background = new SolidColorBrush(Color.FromRgb(25, 39, 30));
                CoreStatusBadge.BorderBrush = new SolidColorBrush(Color.FromRgb(40, 62, 48));
                CoreStatusIcon.Symbol = SymbolRegular.CheckmarkCircle16;
                CoreStatusIcon.Foreground = greenBrush;
                CoreStatusText.Text = "引擎在线 · :9527";
                CoreStatusText.Foreground = greenBrush;
                Log("Go 核心引擎运行正常，端口: 9527");

                await RefreshEngineStatusAsync();
            }
            else
            {
                var redBrush = new SolidColorBrush(Color.FromRgb(232, 139, 136));
                CoreStatusBadge.Background = new SolidColorBrush(Color.FromRgb(42, 24, 25));
                CoreStatusBadge.BorderBrush = new SolidColorBrush(Color.FromRgb(68, 37, 39));
                CoreStatusIcon.Symbol = SymbolRegular.ErrorCircle16;
                CoreStatusIcon.Foreground = redBrush;
                CoreStatusText.Text = "引擎未启动";
                CoreStatusText.Foreground = redBrush;
                Log("警告: 未检测到 Go 核心后端，请检查 vrc-video-core.exe 是否存在");
                ShowInfo("服务异常", "Go 核心服务未能启动，解析与中继功能可能不可用。", NoticeLevel.Error);
            }
        }

        private void MainWindow_Closing(object? sender, System.ComponentModel.CancelEventArgs e)
        {
            _processManager.Stop();
        }

        private async Task RefreshEngineStatusAsync()
        {
            try
            {
                var status = await _apiClient.GetStatusAsync();
                if (status != null)
                {
                    LocalIpComboBox.Items.Clear();
                    foreach (var ip in status.LocalIPs)
                    {
                        LocalIpComboBox.Items.Add(ip);
                    }
                    if (LocalIpComboBox.Items.Count > 0)
                    {
                        LocalIpComboBox.SelectedIndex = 0;
                    }
                }
            }
            catch (Exception ex)
            {
                Log($"获取引擎状态失败: {ex.Message}");
            }
        }

        private string GetSelectedPlatformHint()
        {
            if (PlatformBiliRadio.IsChecked == true) return "bilibili";
            if (PlatformDouyinRadio.IsChecked == true) return "douyin";
            if (PlatformKuaishouRadio.IsChecked == true) return "kuaishou";
            return "auto";
        }

        private async void PasteAndParseBtn_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                string clipText = await NativeClipboard.GetTextAsync();

                if (string.IsNullOrWhiteSpace(clipText))
                {
                    ShowInfo("剪贴板为空", "未能读取到文本，请先复制视频分享链接或口令。", NoticeLevel.Warning);
                    return;
                }

                UrlTextBox.Text = clipText;
                Log($"已从剪贴板读取并覆盖输入: {clipText}");

                await ExecuteParseAsync(clipText, autoCopyDirect: true);
            }
            catch (Exception ex)
            {
                ShowInfo("剪贴板读取异常", ex.Message, NoticeLevel.Error);
            }
        }

        private async void ParseBtn_Click(object sender, RoutedEventArgs e)
        {
            var text = UrlTextBox.Text?.Trim();
            if (string.IsNullOrEmpty(text))
            {
                ShowInfo("输入为空", "请输入或粘贴视频分享链接后再解析。", NoticeLevel.Warning);
                return;
            }
            await ExecuteParseAsync(text, autoCopyDirect: false);
        }

        private async void UrlTextBox_KeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Enter)
            {
                var text = UrlTextBox.Text?.Trim();
                if (!string.IsNullOrEmpty(text))
                {
                    await ExecuteParseAsync(text, autoCopyDirect: false);
                }
            }
        }

        private async Task ExecuteParseAsync(string rawText, bool autoCopyDirect = false)
        {
            SetLoadingState(true);
            ShowInfo("正在解析", "正在通过 Go 并发引擎提取直链…", NoticeLevel.Info);
            Log($"开始解析: {rawText}");

            try
            {
                var hint = GetSelectedPlatformHint();
                var info = await _apiClient.ParseAsync(rawText, hint);
                _currentInfo = info;

                TitleTextBlock.Text = info.Title;
                AuthorTextBlock.Text = $"创作者: {info.Author}";
                PlatformBadgeText.Text = info.PlatformName;
                DurationText.Text = info.DurationStr;
                DurationBadge.Visibility = Visibility.Visible;

                LoadImageAsync(CoverImage, info.CoverUrl, CoverPlaceholder);
                LoadImageAsync(AuthorAvatarImage, info.AuthorAvatar, null);

                QualityComboBox.Items.Clear();
                if (info.Qualities != null && info.Qualities.Count > 0)
                {
                    foreach (var q in info.Qualities)
                    {
                        QualityComboBox.Items.Add(q.DisplayText);
                    }
                    QualityComboBox.SelectedIndex = 0;
                }
                else
                {
                    QualityComboBox.Items.Add(string.IsNullOrEmpty(info.Quality) ? "高清 1080P/720P" : info.Quality);
                    QualityComboBox.SelectedIndex = 0;
                }

                UpdateOutputUrls();
                AnimateResultReveal();

                if (autoCopyDirect)
                {
                    string targetUrl = DirectUrlTextBox.Text?.Trim() ?? string.Empty;
                    if (!string.IsNullOrEmpty(targetUrl))
                    {
                        bool copied = await NativeClipboard.SetTextAsync(targetUrl);
                        if (copied)
                        {
                            Log($"[自动复制] 免防盗链直链已写入剪贴板: {targetUrl}");
                            ShowInfo("解析完成并已复制", $"【{info.PlatformName}】直链已写入剪贴板，回到 VRChat 按 Ctrl+V 即可播放。", NoticeLevel.Success);
                            AnimateCopyFeedback(CopyDirectBtn, CopyDirectLabel, CopyDirectIcon, "复制直链", SymbolRegular.Copy24);
                        }
                        else
                        {
                            Log("自动写入剪贴板受限，请手动点击【复制直链】");
                            ShowInfo("解析完成", $"已成功解析【{info.PlatformName}】直链，可点击【复制直链】复制。", NoticeLevel.Success);
                        }
                    }
                    else
                    {
                        ShowInfo("解析完成", $"已成功解析【{info.PlatformName}】直链，可点击【复制直链】复制。", NoticeLevel.Success);
                    }
                }
                else
                {
                    Log($"解析成功: [{info.PlatformName}] {info.Title}");
                    ShowInfo("解析完成", $"已成功解析【{info.PlatformName}】直链，可点击【复制直链】直接播放。", NoticeLevel.Success);
                }
            }
            catch (Exception ex)
            {
                Log($"解析错误: {ex.Message}");
                ShowInfo("解析失败", ex.Message, NoticeLevel.Error);
            }
            finally
            {
                SetLoadingState(false);
            }
        }

        private void UpdateOutputUrls()
        {
            if (_currentInfo == null) return;

            string targetPlayUrl = _currentInfo.PlayUrl;
            double selectedSizeMb = _currentInfo.SizeMB;
            string selectedLabel = _currentInfo.Quality;

            int selIdx = QualityComboBox.SelectedIndex;
            if (_currentInfo.Qualities != null && selIdx >= 0 && selIdx < _currentInfo.Qualities.Count)
            {
                var q = _currentInfo.Qualities[selIdx];
                targetPlayUrl = q.Url;
                selectedSizeMb = q.SizeMB;
                selectedLabel = q.Label;
            }

            if (selectedSizeMb > 0)
            {
                QualityBadgeText.Text = $"{selectedSizeMb:F1} MB";
                QualityBadge.Visibility = Visibility.Visible;
            }
            else if (!string.IsNullOrEmpty(selectedLabel))
            {
                QualityBadgeText.Text = selectedLabel.Split(' ')[0];
                QualityBadge.Visibility = Visibility.Visible;
            }
            else
            {
                QualityBadge.Visibility = Visibility.Collapsed;
            }

            DirectUrlTextBox.Text = targetPlayUrl;

            string host = LocalIpComboBox.SelectedItem?.ToString() ?? "127.0.0.1";
            VrcUrlTextBox.Text = _apiClient.GetRelayUrl(targetPlayUrl, _currentInfo.Platform, host);
        }

        private void QualityComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            UpdateOutputUrls();
        }

        private void LocalIpComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            UpdateOutputUrls();
        }

        private async void CopyDirectBtn_Click(object sender, RoutedEventArgs e)
        {
            var url = DirectUrlTextBox.Text?.Trim();
            if (string.IsNullOrEmpty(url))
            {
                ShowInfo("未就绪", "尚未解析视频，请先粘贴链接并解析。", NoticeLevel.Warning);
                return;
            }

            if (await NativeClipboard.SetTextAsync(url))
            {
                Log($"已复制官方免防盗链直链到剪贴板: {url}");
                ShowInfo("复制成功", "免防盗链直链已复制！可直接粘贴进 VRChat 播放器。", NoticeLevel.Success);
                AnimateCopyFeedback(CopyDirectBtn, CopyDirectLabel, CopyDirectIcon, "复制直链", SymbolRegular.Copy24);
            }
            else
            {
                ShowInfo("复制失败", "剪贴板暂时被占用，请重试。", NoticeLevel.Error);
            }
        }

        private async void CopyVrcBtn_Click(object sender, RoutedEventArgs e)
        {
            var url = VrcUrlTextBox.Text?.Trim();
            if (string.IsNullOrEmpty(url))
            {
                ShowInfo("未就绪", "中继流地址为空，请先解析视频。", NoticeLevel.Warning);
                return;
            }

            if (await NativeClipboard.SetTextAsync(url))
            {
                Log($"已复制 VRChat 局域网中继流到剪贴板: {url}");
                ShowInfo("复制中继成功", "局域网中继流已复制！适用于网络隔离房间同步。", NoticeLevel.Success);
                AnimateCopyFeedback(CopyVrcBtn, CopyVrcLabel, CopyVrcIcon, "复制中继", SymbolRegular.Share24);
            }
            else
            {
                ShowInfo("复制失败", "剪贴板暂时被占用，请重试。", NoticeLevel.Error);
            }
        }

        private async void CopyTitleBtn_Click(object sender, RoutedEventArgs e)
        {
            var title = TitleTextBlock.Text;
            if (!string.IsNullOrEmpty(title) && title != "等待视频链接，点击上方「粘贴并解析」即可秒出直链")
            {
                if (await NativeClipboard.SetTextAsync(title))
                {
                    ShowInfo("已复制标题", title, NoticeLevel.Success);
                    AnimateCopyFeedback(CopyTitleBtn, CopyTitleLabel, null, "复制视频标题", SymbolRegular.DocumentCopy24);
                }
            }
        }

        private void VerifyBrowserBtn_Click(object sender, RoutedEventArgs e)
        {
            var directUrl = DirectUrlTextBox.Text?.Trim();
            if (string.IsNullOrEmpty(directUrl) && _currentInfo != null)
            {
                directUrl = _currentInfo.PlayUrl;
            }

            if (string.IsNullOrEmpty(directUrl))
            {
                ShowInfo("请先解析", "当前没有可测试的直链，请先解析视频。", NoticeLevel.Warning);
                return;
            }

            try
            {
                Process.Start(new ProcessStartInfo(directUrl) { UseShellExecute = true });
                Log($"已在浏览器中打开直链试播: {directUrl}");
            }
            catch (Exception ex)
            {
                ShowInfo("打开浏览器失败", ex.Message, NoticeLevel.Error);
            }
        }

        private void ClearBtn_Click(object sender, RoutedEventArgs e)
        {
            UrlTextBox.Clear();
            DirectUrlTextBox.Clear();
            VrcUrlTextBox.Clear();
            QualityComboBox.Items.Clear();
            TitleTextBlock.Text = "等待视频链接，点击上方「粘贴并解析」即可秒出直链";
            AuthorTextBlock.Text = "创作者: --";
            PlatformBadgeText.Text = "待解析";
            QualityBadge.Visibility = Visibility.Collapsed;
            DurationBadge.Visibility = Visibility.Collapsed;
            CoverImage.Source = null;
            AuthorAvatarImage.Source = null;
            CoverPlaceholder.Visibility = Visibility.Visible;
            _currentInfo = null;
            ShowInfo("已清空", "输入与当前结果已重置。", NoticeLevel.Info);
        }

        private void SetLoadingState(bool loading)
        {
            PasteAndParseBtn.IsEnabled = !loading;
            ParseBtn.IsEnabled = !loading;
            UrlTextBox.IsEnabled = !loading;
            ParseBtnLabel.Text = loading ? "解析中…" : "解析";

            if (loading)
            {
                LoadingIndicatorBar.Visibility = Visibility.Visible;
                var shimmerAnim = new DoubleAnimation(-180, 960, TimeSpan.FromMilliseconds(1100))
                {
                    RepeatBehavior = RepeatBehavior.Forever,
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseInOut }
                };
                ShimmerTransform.BeginAnimation(TranslateTransform.XProperty, shimmerAnim);
            }
            else
            {
                ShimmerTransform.BeginAnimation(TranslateTransform.XProperty, null);
                LoadingIndicatorBar.Visibility = Visibility.Collapsed;
            }
        }

        private void ShowInfo(string title, string message, NoticeLevel level)
        {
            StatusToastTitle.Text = title;
            StatusToastMessage.Text = message;

            switch (level)
            {
                case NoticeLevel.Success:
                    StatusToastIcon.Symbol = SymbolRegular.CheckmarkCircle24;
                    StatusToastIcon.Foreground = new SolidColorBrush(Color.FromRgb(136, 201, 157));
                    StatusToastBorder.Background = new SolidColorBrush(Color.FromRgb(22, 31, 26));
                    StatusToastBorder.BorderBrush = new SolidColorBrush(Color.FromRgb(38, 56, 44));
                    break;
                case NoticeLevel.Warning:
                    StatusToastIcon.Symbol = SymbolRegular.Warning24;
                    StatusToastIcon.Foreground = new SolidColorBrush(Color.FromRgb(230, 182, 115));
                    StatusToastBorder.Background = new SolidColorBrush(Color.FromRgb(33, 28, 20));
                    StatusToastBorder.BorderBrush = new SolidColorBrush(Color.FromRgb(61, 51, 35));
                    break;
                case NoticeLevel.Error:
                    StatusToastIcon.Symbol = SymbolRegular.ErrorCircle24;
                    StatusToastIcon.Foreground = new SolidColorBrush(Color.FromRgb(232, 139, 136));
                    StatusToastBorder.Background = new SolidColorBrush(Color.FromRgb(36, 22, 23));
                    StatusToastBorder.BorderBrush = new SolidColorBrush(Color.FromRgb(64, 36, 38));
                    break;
                default:
                    StatusToastIcon.Symbol = SymbolRegular.Info24;
                    StatusToastIcon.Foreground = new SolidColorBrush(Color.FromRgb(156, 188, 227));
                    StatusToastBorder.Background = new SolidColorBrush(Color.FromRgb(24, 24, 28));
                    StatusToastBorder.BorderBrush = new SolidColorBrush(Color.FromRgb(41, 40, 47));
                    break;
            }

            try
            {
                var slideAnim = new DoubleAnimation(6.0, 0.0, TimeSpan.FromMilliseconds(220))
                {
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                };
                StatusToastTranslate.BeginAnimation(TranslateTransform.YProperty, slideAnim);
            }
            catch { }
        }

        private void Log(string message)
        {
            var line = $"[{DateTime.Now:HH:mm:ss}] {message}";
            LogTextBlock.Text += (string.IsNullOrEmpty(LogTextBlock.Text) ? "" : "\n") + line;
            LogScrollViewer.ScrollToEnd();
        }

        private void AnimateResultReveal()
        {
            try
            {
                var opacityAnim = new DoubleAnimation(0.25, 1.0, TimeSpan.FromMilliseconds(260))
                {
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                };
                var translateAnim = new DoubleAnimation(12.0, 0.0, TimeSpan.FromMilliseconds(260))
                {
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                };

                ResultCardPanel.BeginAnimation(UIElement.OpacityProperty, opacityAnim);
                ResultCardTranslate.BeginAnimation(TranslateTransform.YProperty, translateAnim);
            }
            catch { }
        }

        private async void AnimateCopyFeedback(
            System.Windows.Controls.Button btn,
            System.Windows.Controls.TextBlock label,
            SymbolIcon? icon,
            string originalLabel,
            SymbolRegular originalSymbol)
        {
            int token = _copyAnimTokens.TryGetValue(btn, out int prev) ? prev + 1 : 1;
            _copyAnimTokens[btn] = token;

            try
            {
                if (btn.RenderTransform is ScaleTransform scale)
                {
                    var bounceAnim = new DoubleAnimation(0.93, 1.0, TimeSpan.FromMilliseconds(220))
                    {
                        EasingFunction = new BackEase { Amplitude = 0.35, EasingMode = EasingMode.EaseOut }
                    };
                    scale.BeginAnimation(ScaleTransform.ScaleXProperty, bounceAnim);
                    scale.BeginAnimation(ScaleTransform.ScaleYProperty, bounceAnim);
                }

                label.Text = "已复制";
                if (icon != null) icon.Symbol = SymbolRegular.Checkmark24;

                await Task.Delay(1300);

                if (_copyAnimTokens.TryGetValue(btn, out int cur) && cur == token)
                {
                    label.Text = originalLabel;
                    if (icon != null) icon.Symbol = originalSymbol;
                    _copyAnimTokens.Remove(btn);
                }
            }
            catch
            {
                label.Text = originalLabel;
                if (icon != null) icon.Symbol = originalSymbol;
                _copyAnimTokens.Remove(btn);
            }
        }

        private static readonly HttpClient _imageHttpClient = new HttpClient(new SocketsHttpHandler
        {
            UseProxy = false,
            Proxy = null,
            PooledConnectionLifetime = TimeSpan.FromMinutes(10),
            EnableMultipleHttp2Connections = true
        })
        {
            Timeout = TimeSpan.FromSeconds(2)
        };

        private async void LoadImageAsync(System.Windows.Controls.Image target, string url, UIElement? placeholder)
        {
            if (string.IsNullOrEmpty(url))
            {
                target.Source = null;
                if (placeholder != null) placeholder.Visibility = Visibility.Visible;
                return;
            }

            try
            {
                var req = new HttpRequestMessage(HttpMethod.Get, url);
                req.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
                if (url.Contains("bilibili") || url.Contains("hdslb"))
                {
                    req.Headers.Add("Referer", "https://www.bilibili.com/");
                }

                var resp = await _imageHttpClient.SendAsync(req, HttpCompletionOption.ResponseContentRead);
                if (resp.IsSuccessStatusCode)
                {
                    var bytes = await resp.Content.ReadAsByteArrayAsync();
                    var bitmap = new BitmapImage();
                    using (var ms = new MemoryStream(bytes))
                    {
                        bitmap.BeginInit();
                        bitmap.CacheOption = BitmapCacheOption.OnLoad;
                        bitmap.StreamSource = ms;
                        bitmap.EndInit();
                    }
                    bitmap.Freeze();

                    target.Source = bitmap;
                    if (placeholder != null) placeholder.Visibility = Visibility.Collapsed;
                }
                else
                {
                    target.Source = null;
                    if (placeholder != null) placeholder.Visibility = Visibility.Visible;
                }
            }
            catch
            {
                target.Source = null;
                if (placeholder != null) placeholder.Visibility = Visibility.Visible;
            }
        }
    }
}
