// AdvPrint Pro v1.7.2 - Windows service wrapper
// AdvMedi by Bit Dream IT - Innovative Healthcare Solutions (MIT)
//
// Compiled ON THE PC by Windows' own csc.exe (nothing downloaded):
//   csc /nologo /target:exe /out:AdvPrintProService.exe
//       /r:System.ServiceProcess.dll AdvPrintProService.cs
//
// Registered as service "AdvPrintPro" (display: "AdvPrint Pro Service").
// OnStart it launches the real hub as a child process:
//   <python> <script> serve
// with ADVPRINT_SERVICE=1 and ADVPRINT_DATA=<installing user's data dir>,
// read from service.json next to this exe (written by the hub before
// elevation). OnStop it kills the child tree. If the child dies, the
// service stops - sc failure recovery restarts it automatically.
//
// Modes:
//   AdvPrintProService.exe              -> run as the service (sc starts)
//   AdvPrintProService.exe install      -> sc create + description + recovery + start
//   AdvPrintProService.exe remove       -> sc stop + sc delete
using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;

public class PHService : ServiceBase
{
    private Process _child;

    public PHService()
    {
        ServiceName = "AdvPrintPro";
        CanPauseAndContinue = false;
        AutoLog = true;
    }

    static void Main(string[] args)
    {
        if (args.Length > 0)
        {
            string a = args[0].ToLowerInvariant();
            if (a == "install") { Install(); return; }
            if (a == "remove") { Remove(); return; }
            Console.WriteLine("usage: AdvPrintProService.exe [install|remove]");
            Environment.Exit(2);
        }
        ServiceBase.Run(new PHService());
    }

    // ---------- service lifecycle ----------
    protected override void OnStart(string[] args)
    {
        try
        {
            string here = AppDomain.CurrentDomain.BaseDirectory;
            string cfgPath = Path.Combine(here, "service.json");
            if (!File.Exists(cfgPath))
                throw new FileNotFoundException("service.json not found", cfgPath);
            string json = File.ReadAllText(cfgPath);
            string py = Grab(json, "python");
            string script = Grab(json, "script");
            string data = Grab(json, "data");
            if (py == "" || script == "")
                throw new InvalidOperationException("service.json missing python/script");

            ProcessStartInfo si = new ProcessStartInfo();
            si.FileName = py;
            si.Arguments = "\"" + script + "\" serve --service";
            si.UseShellExecute = false;
            si.CreateNoWindow = true;
            si.EnvironmentVariables["ADVPRINT_SERVICE"] = "1";
            if (data != "") si.EnvironmentVariables["ADVPRINT_DATA"] = data;
            _child = Process.Start(si);

            // If the hub dies, stop the service so sc recovery restarts it.
            Process c = _child;
            new System.Threading.Thread(delegate()
            {
                try { c.WaitForExit(); } catch (Exception) { }
                try { this.Stop(); } catch (Exception) { }
            }).Start();
        }
        catch (Exception ex)
        {
            try { EventLog.WriteEntry("AdvPrintPro",
                  "OnStart failed: " + ex.Message, EventLogEntryType.Error); }
            catch (Exception) { }
            throw; // SCM marks the start FAILED - visible in services.msc
        }
    }

    protected override void OnStop()
    {
        KillChild();
    }

    private void KillChild()
    {
        if (_child == null) return;
        try
        {
            if (!_child.HasExited)
            {
                // kill the tree: hub may own SumatraPDF / lp children
                ProcessStartInfo si = new ProcessStartInfo();
                si.FileName = "taskkill";
                si.Arguments = "/PID " + _child.Id + " /T /F";
                si.UseShellExecute = false;
                si.CreateNoWindow = true;
                Process.Start(si);
            }
        }
        catch (Exception) { }
        _child = null;
    }

    // ---------- install / remove (must run elevated) ----------
    static int Sc(string args)
    {
        Console.WriteLine("> sc " + args);
        ProcessStartInfo si = new ProcessStartInfo();
        si.FileName = "sc.exe";
        si.Arguments = args;
        si.UseShellExecute = false;
        si.CreateNoWindow = true;
        si.RedirectStandardOutput = true;
        si.RedirectStandardError = true;
        Process p = Process.Start(si);
        string outp = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
        p.WaitForExit(60000);
        if (outp.Trim() != "") Console.WriteLine(outp.Trim());
        return p.ExitCode;
    }

    static void Install()
    {
        string exe = Process.GetCurrentProcess().MainModule.FileName;
        try
        {
            Sc("stop " + Q("AdvPrintPro"));               // clean slate
            Sc("delete " + Q("AdvPrintPro"));
            // ImagePath must keep the inner quotes (paths may contain
            // spaces): binPath= "\"C:\...\AdvPrintProService.exe\" run"
            int rc = Sc("create " + Q("AdvPrintPro") +
                        " binPath= \"\\\"" + exe + "\\\" run\"" +
                        " start= auto" +
                        " obj= LocalSystem" +
                        " DisplayName= " + Q("AdvPrint Pro Service"));
            if (rc != 0) Environment.Exit(rc);
            Sc("description " + Q("AdvPrintPro") + " " +
               Q("Silent print hub (AdvMedi by Bit Dream IT) - prints from any PC in the office. http://127.0.0.1:9235"));
            Sc("failure " + Q("AdvPrintPro") +
               " reset= 86400 actions= restart/60000/restart/60000/restart/60000");
            Sc("start " + Q("AdvPrintPro"));
            Console.WriteLine("AdvPrint Pro Service installed and started.");
            Console.WriteLine("Manage it in services.msc (no tray icon in service mode).");
            Environment.Exit(0);
        }
        catch (Exception ex)
        {
            Console.WriteLine("install failed: " + ex.Message);
            Environment.Exit(1);
        }
    }

    static void Remove()
    {
        try
        {
            Sc("stop " + Q("AdvPrintPro"));
            int rc = Sc("delete " + Q("AdvPrintPro"));
            Console.WriteLine(rc == 0 ? "AdvPrint Pro Service removed."
                                      : ("sc delete returned " + rc));
            Environment.Exit(rc == 0 || rc == 1060 ? 0 : rc); // 1060 = not installed
        }
        catch (Exception ex)
        {
            Console.WriteLine("remove failed: " + ex.Message);
            Environment.Exit(1);
        }
    }

    // Quote a value for the sc.exe command line.
    static string Q(string s)
    {
        return "\"" + (s == null ? "" : s.Replace("\"", "")) + "\"";
    }

    // Pull a string value out of the tiny service.json without a JSON lib.
    static string Grab(string json, string key)
    {
        if (json == null) return "";
        string k = "\"" + key + "\"";
        int i = json.IndexOf(k);
        if (i < 0) return "";
        i = json.IndexOf(':', i + k.Length);
        if (i < 0) return "";
        i = json.IndexOf('"', i + 1);
        if (i < 0) return "";
        int j = json.IndexOf('"', i + 1);
        if (j < 0) return "";
        return json.Substring(i + 1, j - i - 1);
    }
}
