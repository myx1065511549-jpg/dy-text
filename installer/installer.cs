using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

internal static class Installer
{
    private const string TrailerMagic = "DYDASHBOARDZIP01";

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    private static int Main(string[] args)
    {
        bool silent = args.Contains("--silent", StringComparer.OrdinalIgnoreCase);
        bool noLaunch = args.Contains("--no-launch", StringComparer.OrdinalIgnoreCase);
        bool noShortcuts = args.Contains("--no-shortcuts", StringComparer.OrdinalIgnoreCase);
        string target = GetArgument(args, "--target")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "DouyinDashboard");

        if (!silent)
        {
            int answer = MessageBox(
                IntPtr.Zero,
                "安装抖音直播看板？\n\n安装位置：" + target + "\n现有数据库和登录状态会保留。",
                "抖音直播看板安装程序",
                0x24
            );
            if (answer != 6) return 0;
        }

        string tempZip = Path.Combine(Path.GetTempPath(), "douyin-dashboard-" + Guid.NewGuid().ToString("N") + ".zip");
        try
        {
            StopExisting(target);
            ExtractPayload(tempZip, target);
            if (!noShortcuts) CreateShortcuts(target);
            if (!noLaunch)
            {
                Process.Start(new ProcessStartInfo(Path.Combine(target, "douyin-dashboard.exe"))
                {
                    WorkingDirectory = target,
                    UseShellExecute = true,
                });
            }
            if (!silent)
            {
                MessageBox(IntPtr.Zero, "安装完成。", "抖音直播看板", 0x40);
            }
            return 0;
        }
        catch (Exception error)
        {
            if (!silent)
            {
                MessageBox(IntPtr.Zero, "安装失败：" + error.Message, "抖音直播看板", 0x10);
            }
            return 1;
        }
        finally
        {
            try { if (File.Exists(tempZip)) File.Delete(tempZip); } catch { }
        }
    }

    private static string GetArgument(string[] args, string name)
    {
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
        }
        return null;
    }

    private static void StopExisting(string target)
    {
        string stopScript = Path.Combine(target, "停止看板.vbs");
        if (!File.Exists(stopScript)) return;
        using (Process process = Process.Start(new ProcessStartInfo("wscript.exe", "\"" + stopScript + "\" /silent")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        }))
        {
            process.WaitForExit(15000);
        }
    }

    private static void ExtractPayload(string tempZip, string target)
    {
        string installerPath = Process.GetCurrentProcess().MainModule.FileName;
        byte[] expectedMagic = Encoding.ASCII.GetBytes(TrailerMagic);
        long zipLength;
        long zipStart;

        using (FileStream source = File.OpenRead(installerPath))
        using (BinaryReader reader = new BinaryReader(source, Encoding.ASCII, true))
        {
            if (source.Length < 24) throw new InvalidDataException("安装数据不存在。");
            source.Seek(-24, SeekOrigin.End);
            zipLength = reader.ReadInt64();
            byte[] magic = reader.ReadBytes(16);
            if (!magic.SequenceEqual(expectedMagic) || zipLength <= 0 || zipLength > source.Length - 24)
            {
                throw new InvalidDataException("安装数据已损坏。");
            }
            zipStart = source.Length - 24 - zipLength;
            source.Seek(zipStart, SeekOrigin.Begin);
            using (FileStream output = new FileStream(tempZip, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                CopyBytes(source, output, zipLength);
            }
        }

        Directory.CreateDirectory(target);
        string targetPrefix = Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        using (ZipArchive archive = ZipFile.OpenRead(tempZip))
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string destination = Path.GetFullPath(Path.Combine(target, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                if (!destination.StartsWith(targetPrefix, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("安装包中包含非法路径。");
                }
                if (string.IsNullOrEmpty(entry.Name))
                {
                    Directory.CreateDirectory(destination);
                    continue;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using (Stream input = entry.Open())
                using (FileStream output = new FileStream(destination, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    input.CopyTo(output);
                }
                File.SetLastWriteTime(destination, entry.LastWriteTime.LocalDateTime);
            }
        }
    }

    private static void CopyBytes(Stream input, Stream output, long count)
    {
        byte[] buffer = new byte[1024 * 1024];
        while (count > 0)
        {
            int read = input.Read(buffer, 0, (int)Math.Min(buffer.Length, count));
            if (read <= 0) throw new EndOfStreamException();
            output.Write(buffer, 0, read);
            count -= read;
        }
    }

    private static void CreateShortcuts(string target)
    {
        Type shellType = Type.GetTypeFromProgID("WScript.Shell");
        dynamic shell = Activator.CreateInstance(shellType);
        string desktop = shell.SpecialFolders("Desktop");
        string programs = Path.Combine((string)shell.SpecialFolders("Programs"), "抖音直播看板");
        Directory.CreateDirectory(programs);

        CreateShortcut(shell, Path.Combine(desktop, "抖音直播看板.lnk"), Path.Combine(target, "douyin-dashboard.exe"), "", target, "抖音直播实时看板");
        CreateShortcut(shell, Path.Combine(programs, "启动抖音直播看板.lnk"), Path.Combine(target, "douyin-dashboard.exe"), "", target, "启动抖音直播实时看板");
        CreateShortcut(shell, Path.Combine(programs, "停止抖音直播看板.lnk"), "wscript.exe", "\"" + Path.Combine(target, "停止看板.vbs") + "\"", target, "停止抖音直播实时看板");
    }

    private static void CreateShortcut(dynamic shell, string path, string targetPath, string arguments, string workingDirectory, string description)
    {
        dynamic shortcut = shell.CreateShortcut(path);
        shortcut.TargetPath = targetPath;
        shortcut.Arguments = arguments;
        shortcut.WorkingDirectory = workingDirectory;
        shortcut.Description = description;
        shortcut.Save();
    }
}

