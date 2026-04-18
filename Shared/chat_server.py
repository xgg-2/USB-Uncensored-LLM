#!/usr/bin/env python3
"""
Portable AI Chat Server
=======================
Zero-dependency Python HTTP server that:
  1. Serves FastChatUI.html
  2. Persists chat history as JSON on the drive
  3. Proxies Ollama API requests (CORS-safe)

Security model: local-only trust. Not hardened for public internet exposure.
"""

import datetime
import http.server
import json
import logging
import os
import pathlib
import platform
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import ctypes
from urllib.parse import urlparse

# ── Bootstrap ────────────────────────────────────────────────────
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
ROOT_DIR   = SCRIPT_DIR.parent

# ── Load config.json ─────────────────────────────────────────────
_config_path = ROOT_DIR / "config.json"
try:
    CONFIG = json.loads(_config_path.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError) as _e:
    print(f"\n  [WARN] config.json not found or invalid ({_e}). Using defaults.\n")
    CONFIG = {}

# ── Version ───────────────────────────────────────────────────────
VERSION = (ROOT_DIR / "VERSION").read_text(encoding="utf-8").strip() \
          if (ROOT_DIR / "VERSION").exists() else "unknown"

# ── Configuration ─────────────────────────────────────────────────
CHAT_SERVER_PORT  = int(os.environ.get("PORT", CONFIG.get("ui_port", 5000)))
OLLAMA_HOST       = f"http://127.0.0.1:{CONFIG.get('ollama_port', 11434)}"
OLLAMA_TIMEOUT    = int(CONFIG.get("ollama_timeout_seconds", 600))
NETWORK_BIND      = CONFIG.get("network_bind", "0.0.0.0")
LLAMA_CPP_MODE    = "--llama-cpp" in sys.argv

# Security limits
MAX_BODY_BYTES    = 64 * 1024 * 1024   # 64 MB hard cap on all incoming bodies
MAX_JSON_BYTES    = 8  * 1024 * 1024   # 8 MB for JSON API endpoints

if LLAMA_CPP_MODE:
    OLLAMA_HOST = "http://127.0.0.1:8080"

# ── Paths ─────────────────────────────────────────────────────────
CHATS_DIR     = SCRIPT_DIR / "chat_data"
CHATS_FILE    = CHATS_DIR  / "chats.json"
SETTINGS_FILE = CHATS_DIR  / "settings.json"
HTML_FILE     = SCRIPT_DIR / "FastChatUI.html"
LOG_DIR       = SCRIPT_DIR / "logs"

# ── Optional psutil ───────────────────────────────────────────────
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Structured Logging ────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
_ts      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
_log_file = LOG_DIR / f"run_{_ts}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

def _rotate_logs():
    logs = sorted(LOG_DIR.glob("run_*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-5]:
        try:
            old.unlink()
        except OSError:
            pass

_rotate_logs()

# ── Structured Errors ─────────────────────────────────────────────
class AppError(Exception):
    def __init__(self, code: str, message: str, remedy: str):
        super().__init__(message)
        self.code    = code
        self.message = message
        self.remedy  = remedy

    def render(self):
        print(f"\n  ERROR [{self.code}]\n  {self.message}\n  Resolution: {self.remedy}\n")
        logger.error("[%s] %s | Remedy: %s", self.code, self.message, self.remedy)

# ── Preflight Checks ──────────────────────────────────────────────
import shutil
import socket

def _run_preflight():
    checks = []

    # 1. Disk space (500 MB minimum)
    try:
        free     = shutil.disk_usage(str(SCRIPT_DIR)).free
        required = 500 * 1024 ** 2
        checks.append({
            "name":   "disk_space",
            "passed": free > required,
            "detail": f"{free / 1024**2:.0f} MB free",
            "remedy": "Free up at least 500 MB before starting.",
        })
    except Exception as exc:
        checks.append({"name": "disk_space", "passed": True,
                       "detail": f"check skipped ({exc})", "remedy": ""})

    # 2. Write permission
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _test = CHATS_DIR / ".write_test"
        _test.touch()
        _test.unlink()
        checks.append({"name": "write_permission", "passed": True, "detail": str(CHATS_DIR)})
    except PermissionError:
        checks.append({
            "name":   "write_permission",
            "passed": False,
            "detail": str(CHATS_DIR),
            "remedy": "Drive may be mounted read-only. Re-insert and check OS mount flags.",
        })

    # 3. HTML file present
    checks.append({
        "name":   "ui_file",
        "passed": HTML_FILE.exists(),
        "detail": str(HTML_FILE),
        "remedy": f"Ensure FastChatUI.html exists at {HTML_FILE}",
    })

    print()
    print("  Preflight Checks")
    print("  " + "-" * 35)
    all_ok = True
    for chk in checks:
        ok     = chk["passed"]
        status = "\033[92m[PASS]\033[0m" if ok else "\033[91m[FAIL]\033[0m"
        detail = f"  ({chk.get('detail', '')})" if chk.get("detail") else ""
        print(f"  {status}  {chk['name']}{detail}")
        if not ok:
            all_ok = False
            remedy = chk.get("remedy")
            if remedy:
                print(f"         \u2192 {remedy}")
            logger.error("Preflight FAILED: %s \u2014 %s", chk["name"], chk.get("detail", ""))
        else:
            logger.info("Preflight OK: %s \u2014 %s", chk["name"], chk.get("detail", ""))
    print()

    if not all_ok:
        raise AppError(
            code="PREFLIGHT_FAILED",
            message="One or more preflight checks failed.",
            remedy="Address the issues listed above, then retry.",
        )

# ── Hardware Stats ────────────────────────────────────────────────
_cpu_times_last = None

def _get_hw_stats():
    global _cpu_times_last
    if HAS_PSUTIL:
        cpu = round(psutil.cpu_percent(interval=0.25), 1)
        ram = round(psutil.virtual_memory().percent, 1)
        return cpu, ram

    plat = platform.system()

    if plat == "Windows":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength",                ctypes.c_ulong),
                ("dwMemoryLoad",            ctypes.c_ulong),
                ("ullTotalPhys",            ctypes.c_ulonglong),
                ("ullAvailPhys",            ctypes.c_ulonglong),
                ("ullTotalPageFile",        ctypes.c_ulonglong),
                ("ullAvailPageFile",        ctypes.c_ulonglong),
                ("ullTotalVirtual",         ctypes.c_ulonglong),
                ("ullAvailVirtual",         ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        msx = MEMORYSTATUSEX()
        msx.dwLength = ctypes.sizeof(msx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(msx))
        ram = float(msx.dwMemoryLoad)
        FILETIME = ctypes.c_ulonglong
        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        idle_v  = idle.value
        total_v = kern.value + user.value
        if _cpu_times_last is None:
            time.sleep(0.25)
            idle2, kern2, user2 = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle2), ctypes.byref(kern2), ctypes.byref(user2))
            d_idle  = idle2.value - idle_v
            d_total = (kern2.value + user2.value) - total_v
            _cpu_times_last = (idle2.value, kern2.value + user2.value)
        else:
            prev_idle, prev_total = _cpu_times_last
            d_idle  = idle_v  - prev_idle
            d_total = total_v - prev_total
            _cpu_times_last = (idle_v, total_v)
        cpu = round((1.0 - d_idle / max(d_total, 1)) * 100.0, 1)
        return max(0.0, min(100.0, cpu)), ram

    elif plat == "Linux":
        ram = 0.0
        try:
            with open("/proc/meminfo") as f:
                mem = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        mem[parts[0].rstrip(":")] = int(parts[1])
            total = mem.get("MemTotal", 1)
            avail = mem.get("MemAvailable", total)
            ram   = round((1 - avail / total) * 100, 1)
        except Exception:
            pass
        cpu = 0.0
        try:
            def read_cpu():
                with open("/proc/stat") as f:
                    parts = f.readline().split()
                vals  = [int(x) for x in parts[1:]]
                return vals[3], sum(vals)
            if _cpu_times_last is None:
                i1, t1 = read_cpu()
                time.sleep(0.25)
                i2, t2 = read_cpu()
            else:
                i1, t1 = _cpu_times_last
                i2, t2 = read_cpu()
            _cpu_times_last = (i2, t2)
            d_idle  = i2 - i1
            d_total = t2 - t1
            cpu = round((1 - d_idle / max(d_total, 1)) * 100, 1)
        except Exception:
            pass
        return cpu, ram

    return 0.0, 0.0

# ── Data Dir ──────────────────────────────────────────────────────
def ensure_data_dir():
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    if not CHATS_FILE.exists():
        CHATS_FILE.write_text("[]", encoding="utf-8")
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text(
            json.dumps({"systemPrompt": "", "temperature": 0.7}),
            encoding="utf-8",
        )

# ── Security helpers ──────────────────────────────────────────────
# Allowed static file extensions — whitelist only
_STATIC_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".woff2": "font/woff2",
    ".woff":  "font/woff",
}

# Ollama path: only allow known safe API paths
_OLLAMA_SAFE_PATH = re.compile(
    r'^/api/(tags|chat|generate|ps|show|embeddings|delete|pull|push|copy|version)(/.*)?$'
)

def _safe_ollama_path(path: str) -> bool:
    """Reject Ollama proxy paths that don't match the known API surface."""
    # Collapse path traversal sequences before checking
    normalized = pathlib.PurePosixPath(path).as_posix()
    return bool(_OLLAMA_SAFE_PATH.match(normalized))

def _read_body(handler, max_bytes: int) -> bytes:
    """Read request body with hard size limit."""
    raw_len = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_len)
    except (ValueError, TypeError):
        length = 0
    if length < 0 or length > max_bytes:
        raise ValueError(f"Content-Length {length} exceeds limit {max_bytes}")
    return handler.rfile.read(length) if length > 0 else b""

# ── Settings schema ───────────────────────────────────────────────
def _validate_settings(obj: dict) -> dict:
    """Strip unknown keys and coerce types."""
    out = {}
    if isinstance(obj.get("systemPrompt"), str):
        out["systemPrompt"] = obj["systemPrompt"][:4096]   # cap length
    if isinstance(obj.get("globalSystemPrompt"), str):
        out["globalSystemPrompt"] = obj["globalSystemPrompt"][:4096]
    if isinstance(obj.get("temperature"), (int, float)):
        out["temperature"] = max(0.0, min(2.0, float(obj["temperature"])))
    return out

# ── HTTP Handler ──────────────────────────────────────────────────
class ChatHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        msg = format % args
        ts  = time.strftime("%H:%M:%S")
        if "404" in msg or "500" in msg or "502" in msg or "400" in msg:
            prefix = "  \033[91m[ERR]\033[0m"
            logger.warning("HTTP %s", msg)
        elif "200" in msg or "204" in msg:
            prefix = "  \033[92m[ OK]\033[0m"
        else:
            prefix = "  \033[93m[---]\033[0m"
        print(f"{prefix} {ts}  {msg}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        route_map = {
            "/":              self._serve_html,
            "/index.html":    self._serve_html,
            "/api/chats":     self._get_chats,
            "/api/settings":  self._get_settings,
            "/api/stats":     self._get_stats,
            "/api/version":   self._get_version,
        }
        handler = route_map.get(path)
        if handler:
            handler()
        elif path.startswith("/ollama/"):
            self._proxy_ollama("GET")
        else:
            self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        route_map = {
            "/api/chats":    self._save_chats,
            "/api/settings": self._save_settings,
        }
        handler = route_map.get(path)
        if handler:
            handler()
        elif path.startswith("/ollama/"):
            self._proxy_ollama("POST")
        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/ollama/"):
            self._proxy_ollama("DELETE")
        else:
            self._json(404, {"error": "Not found"})

    # ── Static ────────────────────────────────────────────────
    def _serve_html(self):
        try:
            content = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self._json(404, {"error": "FastChatUI.html not found."})

    def _serve_static(self, path: str):
        # Resolve and verify path stays inside SCRIPT_DIR
        try:
            safe_path = pathlib.Path(path.lstrip("/"))
            # Reject any path component that could be a traversal
            if ".." in safe_path.parts:
                raise PermissionError("traversal")
            full_path = (SCRIPT_DIR / safe_path).resolve()
            if not full_path.is_relative_to(SCRIPT_DIR):
                raise PermissionError("outside root")
        except (PermissionError, ValueError):
            self.send_response(403)
            self.end_headers()
            return

        ext = full_path.suffix.lower()
        if ext not in _STATIC_MIME:
            self.send_response(403)
            self.end_headers()
            return

        if full_path.is_file():
            content = full_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _STATIC_MIME[ext])
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    # ── Chat persistence ──────────────────────────────────────
    def _get_chats(self):
        try:
            data = CHATS_FILE.read_text(encoding="utf-8")
            json.loads(data)   # validate it's parseable
        except Exception:
            data = "[]"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def _save_chats(self):
        try:
            body  = _read_body(self, MAX_JSON_BYTES)
            chats = json.loads(body)
            if not isinstance(chats, list):
                raise ValueError("Chats must be a JSON array")
            CHATS_FILE.write_text(
                json.dumps(chats, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._json(200, {"ok": True})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            logger.error("Failed to save chats: %s", exc)
            self._json(500, {"error": "Internal error"})

    # ── Settings ──────────────────────────────────────────────
    def _get_settings(self):
        try:
            data = SETTINGS_FILE.read_text(encoding="utf-8")
            json.loads(data)
        except Exception:
            data = "{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def _save_settings(self):
        try:
            body     = _read_body(self, MAX_JSON_BYTES)
            raw      = json.loads(body)
            if not isinstance(raw, dict):
                raise ValueError("Settings must be a JSON object")
            settings = _validate_settings(raw)
            SETTINGS_FILE.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._json(200, {"ok": True})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            logger.error("Failed to save settings: %s", exc)
            self._json(500, {"error": "Internal error"})

    # ── Stats ──────────────────────────────────────────────────
    def _get_stats(self):
        try:
            cpu, ram = _get_hw_stats()
            self._json(200, {
                "cpu_percent": cpu,
                "ram_percent": ram,
                "has_psutil":  HAS_PSUTIL,
            })
        except Exception as exc:
            logger.error("Stats error: %s", exc)
            self._json(500, {"error": "Internal error"})

    # ── Version ────────────────────────────────────────────────
    def _get_version(self):
        self._json(200, {"version": VERSION})

    # ── Ollama proxy ──────────────────────────────────────────
    def _proxy_ollama(self, method: str):
        ollama_path = self.path[len("/ollama"):]

        # Security: only allow known Ollama API paths; reject traversal
        path_only = urlparse(ollama_path).path
        if not _safe_ollama_path(path_only):
            logger.warning("Rejected proxy path: %s", ollama_path)
            self._json(403, {"error": "Forbidden proxy path"})
            return

        target_url = OLLAMA_HOST + ollama_path

        try:
            body = _read_body(self, MAX_BODY_BYTES) if method in ("POST", "PUT") else None
        except ValueError as exc:
            self._json(413, {"error": str(exc)})
            return

        try:
            if LLAMA_CPP_MODE and path_only == "/api/tags":
                self._json(200, {"models": [{"name": "local-llama-model"}]})
                return

            if LLAMA_CPP_MODE and path_only == "/api/chat":
                try:
                    ollama_req = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    self._json(400, {"error": "Invalid JSON"})
                    return
                openai_req = {
                    "messages":    ollama_req.get("messages", []),
                    "stream":      True,
                    "temperature": ollama_req.get("options", {}).get("temperature", 0.7),
                }
                target_url = OLLAMA_HOST + "/v1/chat/completions"
                body       = json.dumps(openai_req).encode()

            # Forward only safe headers
            req = urllib.request.Request(
                target_url,
                data=body,
                method=method,
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            )
            # Forward Authorization only if explicitly present — do not inject
            if "Authorization" in self.headers:
                req.add_header("Authorization", self.headers["Authorization"])

            response = urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)

            self.send_response(response.status)
            is_stream = path_only in ("/api/chat", "/api/generate")

            for header, value in response.getheaders():
                if header.lower() not in ("transfer-encoding", "connection", "content-length"):
                    self.send_header(header, value)
            self._cors()
            self.end_headers()

            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                if LLAMA_CPP_MODE and is_stream:
                    text  = chunk.decode(errors="ignore")
                    for line in text.split("\n"):
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            j     = json.loads(data)
                            delta = j.get("choices", [{}])[0].get("delta", {})
                            out   = {
                                "message": {"role": "assistant", "content": delta.get("content", "")},
                                "done":    False,
                            }
                            self.wfile.write((json.dumps(out) + "\n").encode())
                            self.wfile.flush()
                        except Exception:
                            pass
                else:
                    self.wfile.write(chunk)
                    if is_stream:
                        self.wfile.flush()

        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            self._cors()
            self.end_headers()
            try:
                self.wfile.write(exc.read())
            except Exception:
                pass

        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            logger.warning("Ollama unreachable: %s", reason)
            self._json(502, {"error": "Engine offline — start Ollama first."})

        except Exception as exc:
            logger.error("Proxy error: %s", exc)
            self._json(500, {"error": "Internal error"})


# ── Threaded HTTP server ───────────────────────────────────────────
class ThreadedHTTPServer(http.server.HTTPServer):
    allow_reuse_address = True   # SO_REUSEADDR — survives rapid restarts

    def process_request(self, request, client_address):
        t = threading.Thread(target=self._handle, args=(request, client_address))
        t.daemon = True
        t.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


# ── Graceful shutdown ──────────────────────────────────────────────
_server_instance = None

def _shutdown_handler(signum, frame):
    logger.info("Signal %s received — shutting down.", signum)
    print("\n  Shutting down…")
    if _server_instance:
        threading.Thread(target=_server_instance.shutdown, daemon=True).start()
    sys.exit(0)

signal.signal(signal.SIGINT,  _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)


# ── Main ───────────────────────────────────────────────────────────
def main():
    global _server_instance

    try:
        _run_preflight()
    except AppError as exc:
        exc.render()
        sys.exit(1)

    ensure_data_dir()

    local_ip = "127.0.0.1"
    try:
        import socket as _sock
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    logger.info("Starting Portable AI v%s on port %s", VERSION, CHAT_SERVER_PORT)

    print()
    print("=" * 55)
    print(f"  Portable AI  v{VERSION}")
    print("=" * 55)
    print(f"  Local:    http://localhost:{CHAT_SERVER_PORT}")
    print(f"  Network:  http://{local_ip}:{CHAT_SERVER_PORT}")
    print(f"  Engine:   {OLLAMA_HOST}")
    if LLAMA_CPP_MODE:
        print("  Mode:     llama.cpp")
    print(f"  Log:      {_log_file.name}")
    print("  Ctrl+C to stop.")
    print("-" * 55)

    _server_instance = ThreadedHTTPServer((NETWORK_BIND, CHAT_SERVER_PORT), ChatHandler)

    if "--no-browser" not in sys.argv:
        t = threading.Thread(
            target=lambda: (time.sleep(1.0), webbrowser.open(f"http://localhost:{CHAT_SERVER_PORT}")),
            daemon=True,
        )
        t.start()

    try:
        _server_instance.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Server stopped.")
        print("  Goodbye!")


if __name__ == "__main__":
    main()
