using System;
using System.Diagnostics;
using System.IO;

internal static class StopDashboard
{
    private static int Main()
    {
        string expectedPath = Path.GetFullPath(Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory,
            "douyin-dashboard.backend.exe"));
        int stopped = 0;

        foreach (Process process in Process.GetProcessesByName("douyin-dashboard.backend"))
        {
            try
            {
                if (!string.Equals(process.MainModule.FileName, expectedPath, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var result = Process.Start(new ProcessStartInfo("taskkill.exe", "/PID " + process.Id + " /T /F")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                });
                result.WaitForExit(10000);
                if (result.ExitCode == 0) stopped++;
            }
            catch {}
            finally
            {
                process.Dispose();
            }
        }

        return stopped > 0 ? 0 : 2;
    }
}

