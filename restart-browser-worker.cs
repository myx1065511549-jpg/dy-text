using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

internal static class RestartBrowserWorker
{
    private const uint SnapshotProcesses = 0x00000002;
    private static readonly IntPtr InvalidHandle = new IntPtr(-1);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry
    {
        public uint Size;
        public uint Usage;
        public uint ProcessId;
        public IntPtr DefaultHeapId;
        public uint ModuleId;
        public uint Threads;
        public uint ParentProcessId;
        public int PriorityBase;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string ExeFile;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32FirstW(IntPtr snapshot, ref ProcessEntry entry);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool Process32NextW(IntPtr snapshot, ref ProcessEntry entry);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    private static int Main()
    {
        string expectedPath = Path.GetFullPath(Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory,
            "douyin-dashboard.backend.exe"));
        var processes = Snapshot();
        int stopped = 0;

        foreach (ProcessEntry entry in processes.Values)
        {
            ProcessEntry parent;
            if (!string.Equals(entry.ExeFile, "douyin-dashboard.backend.exe", StringComparison.OrdinalIgnoreCase)
                || !processes.TryGetValue(entry.ParentProcessId, out parent)
                || !string.Equals(parent.ExeFile, "douyin-dashboard.backend.exe", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (!MatchesPath(entry.ProcessId, expectedPath) || !MatchesPath(parent.ProcessId, expectedPath))
            {
                continue;
            }

            var result = Process.Start(new ProcessStartInfo("taskkill.exe", "/PID " + entry.ProcessId + " /T /F")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            });
            result.WaitForExit(10000);
            if (result.ExitCode == 0) stopped++;
        }

        return stopped > 0 ? 0 : 2;
    }

    private static Dictionary<uint, ProcessEntry> Snapshot()
    {
        var result = new Dictionary<uint, ProcessEntry>();
        IntPtr snapshot = CreateToolhelp32Snapshot(SnapshotProcesses, 0);
        if (snapshot == InvalidHandle) return result;
        try
        {
            var entry = new ProcessEntry { Size = (uint)Marshal.SizeOf(typeof(ProcessEntry)) };
            if (!Process32FirstW(snapshot, ref entry)) return result;
            do
            {
                result[entry.ProcessId] = entry;
                entry.Size = (uint)Marshal.SizeOf(typeof(ProcessEntry));
            }
            while (Process32NextW(snapshot, ref entry));
            return result;
        }
        finally
        {
            CloseHandle(snapshot);
        }
    }

    private static bool MatchesPath(uint processId, string expectedPath)
    {
        try
        {
            using (Process process = Process.GetProcessById((int)processId))
            {
                return string.Equals(process.MainModule.FileName, expectedPath, StringComparison.OrdinalIgnoreCase);
            }
        }
        catch
        {
            return false;
        }
    }
}

