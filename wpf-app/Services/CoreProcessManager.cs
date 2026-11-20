using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

namespace VRCVideoTools.App.Services
{
    public class CoreProcessManager
    {
        private Process? _coreProcess;
        public int Port { get; }

        public CoreProcessManager(int port = 9527)
        {
            Port = port;
        }

        public async Task<bool> EnsureRunningAsync(ApiClient client)
        {
            return await Task.Run(async () =>
            {
                // 1. 查找当前应用目录或上游工作区中的 Go 核心可执行文件
                var baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string? exePath = null;
                var localExe = Path.Combine(baseDir, "vrc-video-core.exe");
                if (File.Exists(localExe))
                {
                    exePath = localExe;
                }
                else
                {
                    var probeDir = new DirectoryInfo(baseDir);
                    for (int i = 0; i < 6 && probeDir != null; i++)
                    {
                        var candidate = Path.Combine(probeDir.FullName, "go-core", "vrc-video-core.exe");
                        if (File.Exists(candidate))
                        {
                            exePath = candidate;
                            break;
                        }
                        probeDir = probeDir.Parent;
                    }
                }

                if (exePath == null)
                {
                    return false;
                }

                // 2. 彻底清理系统残留的旧版本/僵尸 vrc-video-core 进程，杜绝占用 9527 端口导致旧逻辑劫持
                KillExistingCoreProcesses();

                try
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = exePath,
                        Arguments = $"-port {Port}",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        WorkingDirectory = Path.GetDirectoryName(exePath) ?? baseDir
                    };

                    _coreProcess = Process.Start(psi);

                    // 轮询等待核心服务启动
                    for (int i = 0; i < 25; i++)
                    {
                        await Task.Delay(100);
                        if (await client.PingAsync())
                        {
                            return true;
                        }
                    }
                }
                catch
                {
                    // ignored
                }

                return false;
            });
        }

        private void KillExistingCoreProcesses()
        {
            try
            {
                var existing = Process.GetProcessesByName("vrc-video-core");
                foreach (var p in existing)
                {
                    try
                    {
                        p.Kill(entireProcessTree: true);
                        p.WaitForExit(1000);
                    }
                    catch
                    {
                        // ignored
                    }
                }
            }
            catch
            {
                // ignored
            }
        }

        public void Stop()
        {
            try
            {
                if (_coreProcess != null && !_coreProcess.HasExited)
                {
                    _coreProcess.Kill(entireProcessTree: true);
                    _coreProcess.Dispose();
                }
            }
            catch
            {
                // ignored
            }
        }
    }
}
