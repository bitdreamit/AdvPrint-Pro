#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
#  AdvPrint Pro - Windows service wrapper (pure stdlib, ctypes)
# ------------------------------------------------------------
#  Lets the hub run as a REAL Windows service, visible in
#  services.msc as "AdvPrint Pro Service" (short name: AdvPrint).
#
#  Install   : python advprint.py service-install   (UAC prompt)
#  Remove    : python advprint.py service-remove    (UAC prompt)
#  Status    : python advprint.py service-status
#  Debug run : python service_main.py --console     (foreground)
#
#  binPath registered by the installer:
#      "<...>\runtime\python.exe" "<...>\hub\service_main.py"
#
#  NOTE: a Windows service runs before logon and has no desktop -
#  no tray icon in service mode. The DEFAULT auto-run is the normal
#  Startup app (with tray); the service is the optional headless mode.
#  If BOTH are active, the second one to start exits gracefully
#  (port 9235 already in use).
# ============================================================

import os
import sys
import time
import threading

SERVICE_NAME = "AdvPrint"

IS_WIN = sys.platform == "win32"


def _run_hub(stop_event, ready_event=None):
    """Serve the hub until stop_event is set. No tray, no console:
    everything is logged into the data dir (hub.log).

    v2.6.5 SERVICE LIFECYCLE FIX (the "stuck at Starting" fix):
    the old code started the hub in a thread, slept 0.5 s and reported
    RUNNING whenever that thread happened to be alive - a race. It also
    imported + initialised the database INSIDE the thread, so a slow
    first import or a blocked SQLite file made the service sit in
    START_PENDING with no checkpoint. Now:
      phase 1  import + db_init + worker (START_PENDING checkpoints)
      phase 2  bind the port synchronously - success -> READY,
               failure -> STOPPED immediately with the reason in hub.log
      phase 3  serve_forever() on the SCM thread until stop_event
    The service can therefore never hang in START_PENDING: the port
    bind either succeeds within ~1 s or fails fast with a clean
    STOPPED state and a readable log line.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    if base not in sys.path:
        sys.path.insert(0, base)
    os.chdir(base)
    # A service runs as LocalSystem -> ~/.advprint would land in the
    # system profile. Use a machine-wide data dir unless configured.
    os.environ.setdefault(
        "ADVPRINT_DATA",
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                     "AdvPrintPro"))
    import advprint
    advprint.db_init()
    advprint.start_worker()
    try:
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer((advprint.CFG["host"], advprint.CFG["port"]),
                                    advprint.Handler)
    except OSError as e:
        advprint.log("SERVICE: port %d busy (%s) - the Startup copy of"
                     " AdvPrint Pro is already running, so this service"
                     " reports STOPPED (by design only ONE hub owns the"
                     " port). Remove the Startup app or the service,"
                     " never both." % (advprint.CFG["port"], e))
        if ready_event:
            ready_event.set("port-busy")     # wakes the SCM thread NOW
        return
    httpd.daemon_threads = True
    advprint.log("AdvPrint Pro v%s RUNNING as Windows service '%s'"
                 % (advprint.VERSION, SERVICE_NAME))
    if ready_event:
        ready_event.set("ready")             # bind OK -> report RUNNING

    def _watch():
        stop_event.wait()
        advprint.log("AdvPrint Pro service stopping ...")
        try:
            httpd.shutdown()
        except Exception:
            pass

    threading.Thread(target=_watch, daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=1.0)
        httpd.server_close()
    except Exception as e:
        advprint.log("SERVICE FATAL: %s" % e)
        raise


if IS_WIN:

    import ctypes
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    # --- SCM constants (win32) ---
    SERVICE_WIN32_OWN_PROCESS = 0x00000010
    SERVICE_STOPPED = 0x00000001
    SERVICE_START_PENDING = 0x00000002
    SERVICE_STOP_PENDING = 0x00000003
    SERVICE_RUNNING = 0x00000004
    SERVICE_ACCEPT_STOP = 0x00000001
    SERVICE_ACCEPT_SHUTDOWN = 0x00000002
    SERVICE_CONTROL_STOP = 0x00000001
    SERVICE_CONTROL_SHUTDOWN = 0x00000005
    NO_ERROR = 0

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    # void (WINAPI*)(DWORD)  - control handler (return value unused)
    LPHANDLER_FUNCTION = ctypes.WINFUNCTYPE(None, wintypes.DWORD)
    # void (WINAPI*)(DWORD, LPTSTR*)  - service main entry
    LPSERVICE_MAIN_FUNCTION = ctypes.WINFUNCTYPE(
        None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))

    class SERVICE_TABLE_ENTRY(ctypes.Structure):
        _fields_ = [("lpServiceName", wintypes.LPWSTR),
                    ("lpServiceProc", LPSERVICE_MAIN_FUNCTION)]

    _status_handle = None
    _stop_event = threading.Event()
    _worker = None
    _ready = threading.Event()          # v2.6.5: bind result signal
    _result = ["starting"]              # "starting" | "ready" | "port-busy" | error text

    def _report(state, wait=0, checkpoint=0, exit_code=NO_ERROR):
        if not _status_handle:
            return
        ss = SERVICE_STATUS()
        ss.dwServiceType = SERVICE_WIN32_OWN_PROCESS
        ss.dwCurrentState = state
        ss.dwControlsAccepted = (SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN
                                 if state == SERVICE_RUNNING else 0)
        ss.dwWin32ExitCode = exit_code
        ss.dwServiceSpecificExitCode = 0
        ss.dwCheckPoint = checkpoint
        ss.dwWaitHint = wait
        _advapi32.SetServiceStatus(_status_handle, ctypes.byref(ss))

    def _ctrl_handler(control):
        # must return fast - all real work happens on other threads
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            _report(SERVICE_STOP_PENDING, wait=5000, checkpoint=1)
            _stop_event.set()
        else:
            _report(_worker and _worker.is_alive()
                    and SERVICE_RUNNING or SERVICE_STOPPED)

    _CTRL_HANDLER = LPHANDLER_FUNCTION(_ctrl_handler)

    def _worker_main():
        """Thread body: run the hub, translate every outcome into
        _result + _ready so the SCM thread can always report a final
        state (v2.6.5 - no silent thread death, no START_PENDING hang)."""
        try:
            _run_hub(_stop_event, _signal_ready)
        except Exception as e:
            _result[0] = "error: %s" % e
            try:
                import traceback
                import advprint
                advprint.log("SERVICE FATAL in worker:\n%s"
                             % traceback.format_exc())
            except Exception:
                pass
        finally:
            _ready.set()

    def _signal_ready(state):
        _result[0] = state
        _ready.set()

    def _service_main(argc, argv):
        global _status_handle, _worker
        h = _advapi32.RegisterServiceCtrlHandlerW(SERVICE_NAME,
                                                  _CTRL_HANDLER)
        if not h:
            return                      # SCM will time us out - nothing to do
        _status_handle = h
        _stop_event.clear()
        _ready.clear()
        _result[0] = "starting"
        _report(SERVICE_START_PENDING, wait=8000, checkpoint=1)
        try:
            _worker = threading.Thread(target=_worker_main, daemon=True)
            _worker.start()
            # v2.6.5: wait for the REAL bind result instead of guessing.
            # Checkpoint every 2 s so the SCM never thinks we hung; give
            # the import + db + bind up to 30 s on the slowest disk.
            cp = 1
            for _ in range(15):
                if _ready.wait(timeout=2.0):
                    break
                cp += 1
                _report(SERVICE_START_PENDING, wait=8000, checkpoint=cp)
            if _result[0] == "ready" and _worker.is_alive():
                _report(SERVICE_RUNNING)
                while _worker.is_alive():
                    time.sleep(0.5)
            else:
                # port busy / import error / worker died -> clean STOPPED
                # (services.msc shows "Stopped"; the reason is in hub.log)
                _report(SERVICE_STOPPED, exit_code=1)
        finally:
            _report(SERVICE_STOP_PENDING, wait=5000, checkpoint=2)
            for _ in range(40):
                if not _worker or not _worker.is_alive():
                    break
                time.sleep(0.25)
            _report(SERVICE_STOPPED)

    _SERVICE_MAIN = LPSERVICE_MAIN_FUNCTION(_service_main)

    def _dispatch():
        table = (SERVICE_TABLE_ENTRY * 2)()
        table[0].lpServiceName = SERVICE_NAME
        table[0].lpServiceProc = _SERVICE_MAIN
        table[1].lpServiceName = None
        table[1].lpServiceProc = LPSERVICE_MAIN_FUNCTION(0)
        if not _advapi32.StartServiceCtrlDispatcherW(table):
            err = ctypes.get_last_error()
            # 1063 = "not started as a service" (double clicked / console)
            print("This program is the AdvPrint Windows service wrapper.")
            print("It was not started by the Windows service manager "
                  "(error %d)." % err)
            print("")
            print("  Normal hub        : python advprint.py serve")
            print("  Install service   : python advprint.py service-install")
            print("  Debug (foreground): python service_main.py --console")
            sys.exit(1)


def main():
    if not IS_WIN:
        print("service_main.py is the Windows service wrapper.")
        print("On this OS start the hub with:  python advprint.py serve")
        return
    if "--console" in sys.argv or "debug" in sys.argv:
        # foreground debug run - Ctrl+C stops it
        _run_hub(_stop_event)
        return
    _dispatch()


if __name__ == "__main__":
    main()
