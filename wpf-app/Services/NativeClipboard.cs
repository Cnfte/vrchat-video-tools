using System;
using System.Runtime.InteropServices;
using System.Threading.Tasks;

namespace VRCVideoTools.App.Services
{
    public static class NativeClipboard
    {
        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool OpenClipboard(IntPtr hWndNewOwner);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool CloseClipboard();

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool EmptyClipboard();

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr SetClipboardData(uint uFormat, IntPtr hMem);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr GetClipboardData(uint uFormat);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool IsClipboardFormatAvailable(uint uFormat);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GlobalAlloc(uint uFlags, UIntPtr dwBytes);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GlobalLock(IntPtr hMem);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GlobalUnlock(IntPtr hMem);

        private const uint CF_UNICODETEXT = 13;
        private const uint GMEM_MOVEABLE = 0x0002;

        /// <summary>
        /// 原生 Win32 异步无锁写入剪贴板。
        /// 彻底摒弃 WPF 的 OLE OleFlushClipboard (避免在 VRChat 等游戏运行时发生 30 秒 COM RPC 阻塞导致界面卡死)。
        /// </summary>
        public static async Task<bool> SetTextAsync(string text)
        {
            if (string.IsNullOrEmpty(text)) return false;

            return await Task.Run(async () =>
            {
                for (int i = 0; i < 10; i++)
                {
                    if (OpenClipboard(IntPtr.Zero))
                    {
                        try
                        {
                            EmptyClipboard();
                            byte[] bytes = System.Text.Encoding.Unicode.GetBytes(text + "\0");
                            IntPtr hMem = GlobalAlloc(GMEM_MOVEABLE, (UIntPtr)bytes.Length);
                            if (hMem == IntPtr.Zero) return false;

                            IntPtr ptr = GlobalLock(hMem);
                            if (ptr == IntPtr.Zero) return false;

                            Marshal.Copy(bytes, 0, ptr, bytes.Length);
                            GlobalUnlock(hMem);

                            SetClipboardData(CF_UNICODETEXT, hMem);
                            return true;
                        }
                        catch
                        {
                            return false;
                        }
                        finally
                        {
                            CloseClipboard();
                        }
                    }
                    await Task.Delay(25);
                }
                return false;
            });
        }

        /// <summary>
        /// 原生 Win32 异步读取剪贴板纯文本。
        /// </summary>
        public static async Task<string> GetTextAsync()
        {
            return await Task.Run(async () =>
            {
                for (int i = 0; i < 10; i++)
                {
                    if (OpenClipboard(IntPtr.Zero))
                    {
                        try
                        {
                            if (!IsClipboardFormatAvailable(CF_UNICODETEXT))
                            {
                                return string.Empty;
                            }

                            IntPtr hMem = GetClipboardData(CF_UNICODETEXT);
                            if (hMem == IntPtr.Zero) return string.Empty;

                            IntPtr ptr = GlobalLock(hMem);
                            if (ptr == IntPtr.Zero) return string.Empty;

                            try
                            {
                                return Marshal.PtrToStringUni(ptr)?.Trim() ?? string.Empty;
                            }
                            finally
                            {
                                GlobalUnlock(hMem);
                            }
                        }
                        catch
                        {
                            return string.Empty;
                        }
                        finally
                        {
                            CloseClipboard();
                        }
                    }
                    await Task.Delay(25);
                }
                return string.Empty;
            });
        }
    }
}
