using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using Microsoft.Win32;

namespace VRCVideoTools.Installer
{
    public partial class MainWindow : Window
    {
        private int _currentStep = 1;
        private string _targetDir = string.Empty;

        public MainWindow()
        {
            InitializeComponent();

            // 默认安装路径: %LOCALAPPDATA%\Programs\VRC-VideoTools
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            _targetDir = Path.Combine(localApp, "Programs", "VRC-VideoTools");
            InstallPathTextBox.Text = _targetDir;
        }

        private void HeaderBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ButtonState == MouseButtonState.Pressed)
            {
                DragMove();
            }
        }

        private void MinimizeBtn_Click(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

        private void CloseBtn_Click(object sender, RoutedEventArgs e) => Close();

        private void BrowseBtn_Click(object sender, RoutedEventArgs e)
        {
            var dialog = new OpenFolderDialog
            {
                Title = "选择 VRC-VideoTools 安装目录",
                InitialDirectory = _targetDir
            };

            if (dialog.ShowDialog() == true)
            {
                _targetDir = dialog.FolderName;
                InstallPathTextBox.Text = _targetDir;
            }
        }

        private void PrevBtn_Click(object sender, RoutedEventArgs e)
        {
            if (_currentStep == 2)
            {
                ShowStep(1);
            }
        }

        private async void NextBtn_Click(object sender, RoutedEventArgs e)
        {
            if (_currentStep == 1)
            {
                ShowStep(2);
            }
            else if (_currentStep == 2)
            {
                _targetDir = InstallPathTextBox.Text.Trim();
                if (string.IsNullOrEmpty(_targetDir))
                {
                    System.Windows.MessageBox.Show("安装路径不能为空，请指定有效的安装目录。", "提示", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
                    return;
                }

                ShowStep(3);
                await StartInstallationAsync();
            }
            else if (_currentStep == 4)
            {
                if (LaunchAfterInstallCheck.IsChecked == true)
                {
                    var exePath = Path.Combine(_targetDir, "VRCVideoTools.App.exe");
                    if (File.Exists(exePath))
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = exePath,
                            WorkingDirectory = _targetDir,
                            UseShellExecute = true
                        });
                    }
                }
                Close();
            }
        }

        private void CancelBtn_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        private void ShowStep(int step)
        {
            _currentStep = step;
            Step1Panel.Visibility = step == 1 ? Visibility.Visible : Visibility.Collapsed;
            Step2Panel.Visibility = step == 2 ? Visibility.Visible : Visibility.Collapsed;
            Step3Panel.Visibility = step == 3 ? Visibility.Visible : Visibility.Collapsed;
            Step4Panel.Visibility = step == 4 ? Visibility.Visible : Visibility.Collapsed;

            if (step == 1)
            {
                PrevBtn.Visibility = Visibility.Collapsed;
                NextBtn.Content = "下一步";
                NextBtn.Visibility = Visibility.Visible;
                CancelBtn.Visibility = Visibility.Visible;
            }
            else if (step == 2)
            {
                PrevBtn.Visibility = Visibility.Visible;
                NextBtn.Content = "立即安装";
                NextBtn.Visibility = Visibility.Visible;
                CancelBtn.Visibility = Visibility.Visible;
            }
            else if (step == 3)
            {
                PrevBtn.Visibility = Visibility.Collapsed;
                NextBtn.Visibility = Visibility.Collapsed;
                CancelBtn.Visibility = Visibility.Collapsed;
            }
            else if (step == 4)
            {
                PrevBtn.Visibility = Visibility.Collapsed;
                NextBtn.Content = "完成并退出";
                NextBtn.Visibility = Visibility.Visible;
                CancelBtn.Visibility = Visibility.Collapsed;
            }
        }

        private async Task StartInstallationAsync()
        {
            bool checkDotNet = DotNetCheck.IsChecked == true;
            bool desktopShortcut = DesktopShortcutCheck.IsChecked == true;
            bool startMenu = StartMenuCheck.IsChecked == true;
            bool configFirewall = FirewallCheck.IsChecked == true;

            await Task.Run(async () =>
            {
                try
                {
                    // 0. 关闭正在运行的旧版本进程，防止文件占用锁死或端口被旧内核劫持
                    KillRunningInstances();

                    // 1. 检测与安装 .NET 9 桌面运行库
                    if (checkDotNet)
                    {
                        UpdateStatus("正在检测系统 .NET 运行环境...", 5, "正在扫描 WindowsDesktop 运行时...");
                        bool hasDotNet = IsDotNet9Installed();
                        if (hasDotNet)
                        {
                            UpdateStatus("系统 .NET 9 运行环境就绪", 15, "已检测到匹配的 WindowsDesktop 运行时");
                            await Task.Delay(300);
                        }
                        else
                        {
                            await DownloadAndInstallDotNetAsync();
                        }
                    }

                    UpdateStatus("正在创建程序目标目录...", 20, _targetDir);
                    Directory.CreateDirectory(_targetDir);

                    // 2. 解压安装包
                    UpdateStatus("正在读取内置安装载荷...", 25, "payload.zip");
                    var asm = Assembly.GetExecutingAssembly();
                    string? matchedName = null;
                    var allNames = asm.GetManifestResourceNames();
                    foreach (var name in allNames)
                    {
                        if (name.EndsWith("payload.zip", StringComparison.OrdinalIgnoreCase))
                        {
                            matchedName = name;
                            break;
                        }
                    }

                    if (string.IsNullOrEmpty(matchedName))
                    {
                        throw new Exception($"安装包损坏：未找到内置 payload 载荷 (清单包含: {string.Join(", ", allNames)})");
                    }

                    using var zipStream = asm.GetManifestResourceStream(matchedName);
                    if (zipStream == null)
                    {
                        throw new Exception($"未能加载安装包内置资源: {matchedName}");
                    }

                    using var archive = new ZipArchive(zipStream, ZipArchiveMode.Read);
                    int total = archive.Entries.Count;
                    int current = 0;

                    foreach (var entry in archive.Entries)
                    {
                        current++;
                        if (string.IsNullOrEmpty(entry.Name)) continue; // 目录项

                        var destPath = Path.Combine(_targetDir, entry.FullName);
                        var dir = Path.GetDirectoryName(destPath);
                        if (!string.IsNullOrEmpty(dir))
                        {
                            Directory.CreateDirectory(dir);
                        }

                        int progress = 30 + (int)((current / (double)total) * 45);
                        UpdateStatus($"正在释放: {entry.Name}", progress, destPath);

                        entry.ExtractToFile(destPath, overwrite: true);
                        await Task.Delay(20);
                    }

                    // 3. 防火墙配置
                    if (configFirewall)
                    {
                        UpdateStatus("正在配置 Windows 防火墙规则...", 80, "开放入站 TCP 9527 端口");
                        ConfigureFirewallRule();
                    }

                    // 4. 快捷方式创建
                    var exePath = Path.Combine(_targetDir, "VRCVideoTools.App.exe");
                    if (desktopShortcut)
                    {
                        UpdateStatus("正在创建桌面快捷方式...", 88, "Desktop");
                        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                        string lnk = Path.Combine(desktop, "VRC-VideoTools.lnk");
                        CreateShortcut(lnk, exePath);
                    }

                    if (startMenu)
                    {
                        UpdateStatus("正在创建开始菜单项...", 95, "Start Menu");
                        string startFolder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "VRC-VideoTools");
                        Directory.CreateDirectory(startFolder);
                        string lnk = Path.Combine(startFolder, "VRC-VideoTools.lnk");
                        CreateShortcut(lnk, exePath);
                    }

                    UpdateStatus("安装顺利完成！", 100, "就绪");
                    await Task.Delay(400);

                    Dispatcher.Invoke(() => ShowStep(4));
                }
                catch (Exception ex)
                {
                    Dispatcher.Invoke(() =>
                    {
                        System.Windows.MessageBox.Show($"安装过程遇到错误:\n{ex.Message}", "安装失败", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
                        Close();
                    });
                }
            });
        }

        private static void KillRunningInstances()
        {
            try
            {
                foreach (var p in Process.GetProcessesByName("vrc-video-core"))
                {
                    try { p.Kill(true); p.WaitForExit(1000); } catch { }
                }
                foreach (var p in Process.GetProcessesByName("VRCVideoTools.App"))
                {
                    try { p.Kill(true); p.WaitForExit(1000); } catch { }
                }
            }
            catch { }
        }

        private bool IsDotNet9Installed()
        {
            try
            {
                // 1. 检查注册表
                using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.WindowsDesktop.App"))
                {
                    if (key != null)
                    {
                        foreach (var sub in key.GetSubKeyNames())
                        {
                            if (sub.StartsWith("9.") || sub.StartsWith("10.")) return true;
                        }
                    }
                }
            }
            catch { }

            try
            {
                // 2. 检查默认物理路径
                var defaultPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "dotnet", "shared", "Microsoft.WindowsDesktop.App");
                if (Directory.Exists(defaultPath))
                {
                    foreach (var dir in Directory.GetDirectories(defaultPath))
                    {
                        var name = Path.GetFileName(dir);
                        if (name.StartsWith("9.") || name.StartsWith("10.")) return true;
                    }
                }
            }
            catch { }

            try
            {
                // 3. 执行 dotnet --list-runtimes
                var psi = new ProcessStartInfo
                {
                    FileName = "dotnet",
                    Arguments = "--list-runtimes",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                using var p = Process.Start(psi);
                if (p != null)
                {
                    string output = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(3000);
                    if (output.Contains("Microsoft.WindowsDesktop.App 9.") || output.Contains("Microsoft.WindowsDesktop.App 10."))
                    {
                        return true;
                    }
                }
            }
            catch { }

            return false;
        }

        private async Task DownloadAndInstallDotNetAsync()
        {
            string url = "https://aka.ms/dotnet/9.0/windowsdesktop-runtime-win-x64.exe";
            UpdateStatus("正在从微软官方下载 .NET 9 桌面运行库...", 6, url);
            string tempInstaller = Path.Combine(Path.GetTempPath(), "windowsdesktop-runtime-9.0-win-x64.exe");

            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromMinutes(6);
                using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead);
                response.EnsureSuccessStatusCode();

                long totalBytes = response.Content.Headers.ContentLength ?? 60_000_000;
                using var contentStream = await response.Content.ReadAsStreamAsync();
                using var fileStream = new FileStream(tempInstaller, FileMode.Create, FileAccess.Write, FileShare.None, 16384, true);

                var buffer = new byte[32768];
                long totalRead = 0;
                int bytesRead;

                while ((bytesRead = await contentStream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                {
                    await fileStream.WriteAsync(buffer, 0, bytesRead);
                    totalRead += bytesRead;
                    int progress = 6 + (int)((totalRead / (double)totalBytes) * 12);
                    double mbRead = totalRead / 1024.0 / 1024.0;
                    double mbTotal = totalBytes / 1024.0 / 1024.0;
                    UpdateStatus($"正在下载 .NET 9 桌面运行库 ({mbRead:F1}MB / {mbTotal:F1}MB)...", progress, tempInstaller);
                }
            }

            UpdateStatus("正在静默安装 .NET 9 桌面运行库，请稍候...", 18, "执行微软官方静默安装程序");
            var psi = new ProcessStartInfo
            {
                FileName = tempInstaller,
                Arguments = "/install /quiet /norestart",
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var proc = Process.Start(psi);
            if (proc != null)
            {
                await proc.WaitForExitAsync();
            }

            try
            {
                if (File.Exists(tempInstaller)) File.Delete(tempInstaller);
            }
            catch { }
            UpdateStatus(".NET 9 桌面运行库安装完毕！", 20, "系统运行环境已就绪");
            await Task.Delay(300);
        }

        private void UpdateStatus(string status, int progress, string detail)
        {
            Dispatcher.Invoke(() =>
            {
                InstallStatusText.Text = status;
                InstallProgressBar.Value = progress;
                InstallDetailText.Text = detail;
            });
        }

        private void ConfigureFirewallRule()
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "netsh",
                    Arguments = "advfirewall firewall add rule name=\"VRC-VideoTools Proxy\" dir=in action=allow protocol=TCP localport=9527",
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                using var p = Process.Start(psi);
                p?.WaitForExit(3000);
            }
            catch
            {
                // ignored
            }
        }

        private void CreateShortcut(string shortcutPath, string targetExePath)
        {
            try
            {
                Type? shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType != null)
                {
                    dynamic shell = Activator.CreateInstance(shellType)!;
                    dynamic shortcut = shell.CreateShortcut(shortcutPath);
                    shortcut.TargetPath = targetExePath;
                    shortcut.IconLocation = targetExePath + ",0";
                    shortcut.WorkingDirectory = Path.GetDirectoryName(targetExePath);
                    shortcut.Description = "VRC-VideoTools 视频直链解析与流媒体中继器";
                    shortcut.Save();
                }
            }
            catch
            {
                // ignored
            }
        }
    }
}