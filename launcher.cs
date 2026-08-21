using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Threading;

internal static class Launcher
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    private static void Main()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string backend = Path.Combine(baseDir, "douyin-dashboard.backend.exe");
        string node = Path.Combine(baseDir, "_internal", "playwright", "driver", "node.exe");
        string helper = Path.Combine(baseDir, "login_helper.js");

        if (!File.Exists(backend) || !File.Exists(node) || !File.Exists(helper))
        {
            MessageBox(IntPtr.Zero, "程序文件不完整，请保留整个项目目录。", "抖音直播看板", 0x10);
            return;
        }

        bool dashboardReady = PortOpen(8848);
        if (!PortOpen(8849))
        {
            StartHidden(node, "\"" + helper + "\"", baseDir);
            Thread.Sleep(150);
        }

        if (!dashboardReady)
        {
            StartHidden(backend, "", baseDir);
        }
        else
        {
            Process.Start(new ProcessStartInfo("http://127.0.0.1:8848/dashboard")
            {
                UseShellExecute = true,
            });
        }
    }

    private static bool PortOpen(int port)
    {
        try
        {
            using (var client = new TcpClient())
            {
                IAsyncResult result = client.BeginConnect("127.0.0.1", port, null, null);
                bool connected = result.AsyncWaitHandle.WaitOne(250);
                if (!connected) return false;
                client.EndConnect(result);
                return true;
            }
        }
        catch
        {
            return false;
        }
    }

    private static void StartHidden(string fileName, string arguments, string workingDirectory)
    {
        Process.Start(new ProcessStartInfo(fileName, arguments)
        {
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        });
    }
}

