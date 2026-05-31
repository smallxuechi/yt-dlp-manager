"""
yt-dlp Web 管理器
运行: python server.py
"""

import os
import sys
import json
import subprocess
import threading
import time
import uuid
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# ── 修复 Windows 控制台中文乱码 ──────────────────────────────────────────────
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 日志配置 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── SSE 客户端管理 ─────────────────────────────────────────────────────────────
sse_clients = set()
sse_lock = threading.Lock()


# ── 多线程 HTTP 服务器 ────────────────────────────────────────────────────────
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程的 HTTP 服务器，让每个请求在独立线程中处理"""
    daemon_threads = True


def broadcast_sse(message: dict) -> None:
    """广播消息到所有 SSE 客户端"""
    with sse_lock:
        clients_copy = list(sse_clients)
    if clients_copy:
        data = json.dumps(message, ensure_ascii=False)
        for client in clients_copy:
            try:
                client.send(f"data: {data}\n\n")
            except Exception:
                pass  # 忽略发送失败的客户端

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DATA_FILE = os.path.join(BASE_DIR, "data.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
COOKIES_FILE = os.path.join(TOOLS_DIR, "cookies.txt")  # 默认路径，也会自动查找其他名称


def find_cookies_file() -> str | None:
    """
    自动在 tools 目录中查找 cookies 文件。
    查找顺序：
      1. cookies.txt（标准名称）
      2. 任意 *_cookies.txt（插件默认导出格式，如 www.youtube.com_cookies.txt）
      3. 任意 .txt 文件且包含 Netscape HTTP Cookie 头
    返回找到的文件绝对路径，找不到返回 None。
    """
    # 1. 标准名称
    standard = os.path.join(TOOLS_DIR, "cookies.txt")
    if os.path.exists(standard):
        return standard

    # 2. *_cookies.txt 模式（Get cookies.txt LOCALLY 插件默认命名）
    try:
        for fname in os.listdir(TOOLS_DIR):
            if fname.endswith("_cookies.txt"):
                return os.path.join(TOOLS_DIR, fname)
    except OSError:
        pass

    # 3. 任意 .txt 文件包含 Netscape Cookie 标识头
    try:
        for fname in os.listdir(TOOLS_DIR):
            if not fname.endswith(".txt"):
                continue
            fpath = os.path.join(TOOLS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline()
                if "Netscape HTTP Cookie" in first_line:
                    return fpath
            except OSError:
                pass
    except OSError:
        pass

    return None

YTDLP_EXE = os.path.join(TOOLS_DIR, "yt-dlp.exe")
FFMPEG_EXE = os.path.join(TOOLS_DIR, "ffmpeg.exe")

for d in [DOWNLOADS_DIR, LOGS_DIR]:
    os.makedirs(d, exist_ok=True)

# ── 并发控制 ──────────────────────────────────────────────────────────────────
# 用字典追踪正在运行的进程，key = task_id，value = Popen 对象
# 这样才能真正"取消"下载（kill 进程）
active_processes: dict[str, subprocess.Popen] = {}

# 内存中缓存进度，避免频繁读写磁盘造成竞争条件
# key = task_id，value = 最新进度字符串
progress_cache: dict[str, str] = {}

data_lock = threading.Lock()


# ── SSE 客户端 ──────────────────────────────────────────────────────────────────
class SSEClient:
    """SSE 客户端封装，用于发送 Server-Sent Events"""
    def __init__(self, wfile):
        self.wfile = wfile

    def send(self, data: str) -> None:
        try:
            self.wfile.write(data.encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def keep_alive(self) -> None:
        try:
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()
        except Exception:
            pass


# ── 数据读写 ──────────────────────────────────────────────────────────────────
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"读取 data.json 失败: {e}")
    return {"tasks": [], "history": []}


def save_data(data: dict) -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"写入 data.json 失败: {e}")


# ── 设置读写 ──────────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: dict = {
    "proxy_enabled": False,
    "proxy_url": "http://127.0.0.1:10808",
    "concurrent_fragments": 8,
}


def load_settings() -> dict:
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings.update(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"读取 settings.json 失败: {e}")
    return settings


def save_settings(settings: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"写入 settings.json 失败: {e}")


# ── 国内网站检测（跳过代理） ──────────────────────────────────────────────────
DOMESTIC_DOMAINS: set[str] = {
    "bilibili.com", "b23.tv",
    "youku.com",
    "iqiyi.com", "iq.com",
    "weibo.com", "weibo.cn",
    "douyin.com",
    "mgtv.com",
    "v.qq.com",
    "acfun.cn",
    "ixigua.com",
    "huya.com",
    "douyu.com",
    "kuaishou.com",
    "yinyuetai.com",
    "xvideos.com",
}


def is_domestic_url(url: str) -> bool:
    """判断 URL 是否属于国内网站，国内网站下载时跳过代理。"""
    try:
        hostname = (urlparse(url).hostname or "").lower()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        for domain in DOMESTIC_DOMAINS:
            if hostname == domain or hostname.endswith("." + domain):
                return True
    except Exception:
        pass
    return False


# ── 任务数据结构 ──────────────────────────────────────────────────────────────
class DownloadTask:
    def __init__(
        self,
        url: str,
        format_option: str = "best",
        filename_template: str = "%(title)s.%(ext)s",
        cookie_browser: str = "",
    ):
        self.id = str(uuid.uuid4())[:8]
        self.url = url
        self.format_option = format_option
        self.filename_template = filename_template
        self.cookie_browser = cookie_browser  # 新增：cookies 来源浏览器
        self.status = "pending"
        self.progress = ""
        self.output_path = ""
        self.error = ""
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "format_option": self.format_option,
            "filename_template": self.filename_template,
            "cookie_browser": self.cookie_browser,
            "status": self.status,
            "progress": self.progress,
            "output_path": self.output_path,
            "error": self.error,
            "created_at": self.created_at,
        }


# ── 下载线程 ──────────────────────────────────────────────────────────────────
def run_download(
    task_id: str,
    url: str,
    format_option: str,
    filename_template: str,
    cookie_browser: str,
) -> None:
    """在独立线程中运行 yt-dlp 下载，结束后更新状态。"""

    # 标记为 running
    with data_lock:
        data = load_data()
        task = next((t for t in data["tasks"] if t["id"] == task_id), None)
        if not task:
            logger.warning(f"[{task_id}] 任务不存在，已跳过")
            return
        task["status"] = "running"
        save_data(data)
        broadcast_sse({"type": "task_update", "task": task})

    output_template = os.path.join(DOWNLOADS_DIR, filename_template)
    log_file = os.path.join(LOGS_DIR, f"{task_id}.log")

    # 构建命令
    cmd = [
        YTDLP_EXE,
        url,
        "-o", output_template,
        "--newline",
        "--progress",
        "--no-playlist",
        "--ffmpeg-location", TOOLS_DIR,  # 指定本地 ffmpeg 目录
        # ── YouTube n 参数反爬求解 ────────────────────────────────
        # Node.js 已安装，用它来解密 YouTube 的 n 参数混淆
        "--js-runtimes", "node",
        # 允许 yt-dlp 自动下载 EJS 求解器脚本（仅首次需要网络）
        "--remote-components", "ejs:github",
    ]

    # 并发分片加速（对 YouTube/B站 DASH 格式效果显著）
    settings = load_settings()
    cmd.extend(["--concurrent-fragments", str(settings.get("concurrent_fragments", 8))])

    # 代理：仅对国外网站启用
    if settings.get("proxy_enabled") and not is_domestic_url(url):
        proxy_url_val = settings.get("proxy_url", "http://127.0.0.1:10808")
        cmd.extend(["--proxy", proxy_url_val])
        logger.info(f"[{task_id}] 走代理: {proxy_url_val}")
    elif is_domestic_url(url):
        logger.info(f"[{task_id}] 国内网站，跳过代理")

    # ✅ 修复：format 参数必须拆成两个独立元素
    if format_option == "audio":
        cmd.extend(["-x", "--audio-format", "mp3"])
    elif format_option == "bestvideo":
        cmd.extend(["-f", "bestvideo+bestaudio/best"])
    else:
        cmd.extend(["-f", "b"])  # "b" 等同于 "best"，且不触发 yt-dlp 弃用警告

    # Cookies 支持：两种模式
    if cookie_browser == "file":
        # 模式一：使用 cookies.txt 文件（Get cookies.txt LOCALLY 插件导出）
        cookies_path = find_cookies_file()
        if cookies_path:
            cmd.extend(["--cookies", cookies_path])
            logger.info(f"[{task_id}] 使用 cookies 文件: {os.path.basename(cookies_path)}")
        else:
            logger.warning(f"[{task_id}] 未在 tools 目录找到 cookies 文件")
    elif cookie_browser and cookie_browser != "none":
        # 模式二：从浏览器读取
        cmd.extend(["--cookies-from-browser", cookie_browser])
        logger.info(f"[{task_id}] 使用 {cookie_browser} 的 Cookies")

    logger.info(f"[{task_id}] 开始下载: {url}")

    try:
        with open(log_file, "w", encoding="utf-8") as log_f:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # ✅ 修复：把进程存入字典，取消时可以 kill
            active_processes[task_id] = process

            line_count = 0
            for line in process.stdout:
                log_f.write(line)
                log_f.flush()

                stripped = line.strip()
                if stripped:
                    # 内存缓存最新进度
                    progress_cache[task_id] = stripped[:200]

                line_count += 1
                # ✅ 修复：每 15 行才写一次磁盘，避免频繁 IO 与竞争条件
                if line_count % 15 == 0:
                    with data_lock:
                        d = load_data()
                        t = next((x for x in d["tasks"] if x["id"] == task_id), None)
                        if t:
                            t["progress"] = progress_cache.get(task_id, "")
                            save_data(d)
                            # 实时推送进度（不等待每15行）
                            broadcast_sse({"type": "progress", "task_id": task_id, "progress": t["progress"]})

            process.wait()

        active_processes.pop(task_id, None)
        progress_cache.pop(task_id, None)

        # 根据退出码更新最终状态
        with data_lock:
            data = load_data()
            task = next((t for t in data["tasks"] if t["id"] == task_id), None)
            if task:
                if process.returncode == 0:
                    task["status"] = "completed"
                    task["progress"] = "下载完成"
                    # 移入历史记录
                    data["history"].insert(0, task.copy())
                    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
                    logger.info(f"[{task_id}] ✅ 下载成功")
                else:
                    task["status"] = "failed"
                    task["error"] = f"yt-dlp 退出码: {process.returncode}"
                    logger.error(f"[{task_id}] ❌ 下载失败，退出码: {process.returncode}")
                save_data(data)
                broadcast_sse({"type": "task_update", "task": task, "action": "completed"})

    except Exception as e:
        active_processes.pop(task_id, None)
        progress_cache.pop(task_id, None)
        logger.exception(f"[{task_id}] 下载异常: {e}")

        with data_lock:
            data = load_data()
            task = next((t for t in data["tasks"] if t["id"] == task_id), None)
            if task:
                task["status"] = "failed"
                task["error"] = str(e)
                save_data(data)
                broadcast_sse({"type": "task_update", "task": task, "action": "failed"})


# ── HTTP 处理器 ───────────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):

    def log_message(self, format: str, *args) -> None:
        # 屏蔽 SimpleHTTPRequestHandler 自带的每次请求日志，减少干扰
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/tasks":
            with data_lock:
                data = load_data()
            tasks = data["tasks"]
            # 将内存中的实时进度合并进返回结果（不写磁盘）
            for t in tasks:
                if t["id"] in progress_cache:
                    t["progress"] = progress_cache[t["id"]]
            self.send_json(tasks)

        elif parsed.path == "/api/history":
            with data_lock:
                data = load_data()
            self.send_json(data["history"][:50])

        elif parsed.path == "/api/check-cookies":
            # 检测 cookies 文件是否存在，自动识别插件导出的文件名
            cookies_path = find_cookies_file()
            exists = cookies_path is not None
            size = os.path.getsize(cookies_path) if exists else 0
            self.send_json({
                "exists": exists,
                "filename": os.path.basename(cookies_path) if exists else None,
                "path": cookies_path,
                "size_kb": round(size / 1024, 1),
            })

        elif parsed.path == "/api/logs":
            params = parse_qs(parsed.query)
            task_id = params.get("id", [None])[0]
            if task_id:
                log_file = os.path.join(LOGS_DIR, f"{task_id}.log")
                if os.path.exists(log_file):
                    try:
                        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(content.encode("utf-8"))
                        return
                    except OSError as e:
                        logger.error(f"读取日志文件失败: {e}")
            self.send_error(404)

        # ── SSE 实时推送 ─────────────────────────────────────────────────────
        elif parsed.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # 创建 SSE 客户端
            client = SSEClient(self.wfile)
            with sse_lock:
                sse_clients.add(client)

            # 保持连接 alive，定期发送心跳
            try:
                while True:
                    time.sleep(30)
                    client.keep_alive()
            except Exception:
                pass
            finally:
                with sse_lock:
                    sse_clients.discard(client)
            return

        # ── 文件管理 API ─────────────────────────────────────────────────────
        elif parsed.path == "/api/files":
            files = []
            try:
                for fname in os.listdir(DOWNLOADS_DIR):
                    fpath = os.path.join(DOWNLOADS_DIR, fname)
                    if os.path.isfile(fpath):
                        stat = os.stat(fpath)
                        size = stat.st_size
                        # 格式化大小
                        if size < 1024:
                            size_display = f"{size} B"
                        elif size < 1024 * 1024:
                            size_display = f"{size / 1024:.1f} KB"
                        elif size < 1024 * 1024 * 1024:
                            size_display = f"{size / (1024 * 1024):.1f} MB"
                        else:
                            size_display = f"{size / (1024 * 1024 * 1024):.2f} GB"
                        files.append({
                            "name": fname,
                            "size": size,
                            "size_display": size_display,
                            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                        })
            except OSError as e:
                logger.error(f"读取下载目录失败: {e}")
            # 按修改时间倒序
            files.sort(key=lambda x: x["modified"], reverse=True)
            self.send_json(files)

        elif parsed.path == "/api/settings":
            self.send_json(load_settings())

        elif parsed.path == "/":
            self.path = "/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        else:
            return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/add":
            params = self._read_form()
            url = params.get("url", [""])[0].strip()
            format_option = params.get("format", ["best"])[0]
            cookie_browser = params.get("cookie_browser", ["none"])[0]

            if not url:
                self.send_json({"success": False, "error": "URL 不能为空"})
                return

            task = DownloadTask(url, format_option, cookie_browser=cookie_browser)

            with data_lock:
                data = load_data()
                data["tasks"].append(task.to_dict())
                save_data(data)

            thread = threading.Thread(
                target=run_download,
                args=(task.id, url, format_option, task.filename_template, cookie_browser),
                daemon=True,
            )
            thread.start()

            logger.info(f"[{task.id}] 任务已创建: {url}")
            self.send_json({"success": True, "id": task.id})

        elif parsed.path == "/api/cancel":
            params = self._read_form()
            task_id = params.get("id", [""])[0]

            # ✅ 修复：真正 kill 进程，而不只是删记录
            process = active_processes.pop(task_id, None)
            if process:
                try:
                    process.terminate()
                    logger.info(f"[{task_id}] 已发送终止信号")
                except OSError as e:
                    logger.warning(f"[{task_id}] 终止进程失败: {e}")

            with data_lock:
                data = load_data()
                data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
                save_data(data)

            self.send_json({"success": True})

        elif parsed.path == "/api/clear-history":
            with data_lock:
                data = load_data()
                data["history"] = []
                save_data(data)
            self.send_json({"success": True})

        elif parsed.path == "/api/delete-history":
            params = self._read_form()
            task_id = params.get("id", [""])[0]

            with data_lock:
                data = load_data()
                data["history"] = [t for t in data["history"] if t["id"] != task_id]
                save_data(data)
            self.send_json({"success": True})

        elif parsed.path == "/api/clear-failed":
            # 新增：清除所有失败任务
            with data_lock:
                data = load_data()
                data["tasks"] = [t for t in data["tasks"] if t["status"] != "failed"]
                save_data(data)
            self.send_json({"success": True})

        # ── 文件管理 API ─────────────────────────────────────────────────────
        elif parsed.path == "/api/files/delete":
            params = self._read_form()
            filename = params.get("name", [""])[0]
            if filename:
                fpath = os.path.join(DOWNLOADS_DIR, filename)
                if os.path.exists(fpath) and os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        logger.info(f"已删除文件: {filename}")
                        self.send_json({"success": True})
                    except OSError as e:
                        self.send_json({"success": False, "error": str(e)})
                else:
                    self.send_json({"success": False, "error": "文件不存在"})
            else:
                self.send_json({"success": False, "error": "文件名不能为空"})

        elif parsed.path == "/api/files/rename":
            params = self._read_form()
            old_name = params.get("old_name", [""])[0]
            new_name = params.get("new_name", [""])[0]
            if old_name and new_name:
                old_path = os.path.join(DOWNLOADS_DIR, old_name)
                new_path = os.path.join(DOWNLOADS_DIR, new_name)
                if os.path.exists(old_path) and os.path.isfile(old_path):
                    if not os.path.exists(new_path):
                        try:
                            os.rename(old_path, new_path)
                            logger.info(f"已重命名: {old_name} -> {new_name}")
                            self.send_json({"success": True})
                        except OSError as e:
                            self.send_json({"success": False, "error": str(e)})
                    else:
                        self.send_json({"success": False, "error": "目标文件名已存在"})
                else:
                    self.send_json({"success": False, "error": "源文件不存在"})
            else:
                self.send_json({"success": False, "error": "文件名不能为空"})

        elif parsed.path == "/api/files/open":
            params = self._read_form()
            filename = params.get("name", [""])[0]
            if filename:
                fpath = os.path.join(DOWNLOADS_DIR, filename)
                if os.path.exists(fpath) and os.path.isfile(fpath):
                    try:
                        os.startfile(fpath)
                        self.send_json({"success": True})
                    except OSError as e:
                        self.send_json({"success": False, "error": str(e)})
                else:
                    self.send_json({"success": False, "error": "文件不存在"})
            else:
                self.send_json({"success": False, "error": "文件名不能为空"})

        elif parsed.path == "/api/settings":
            params = self._read_form()
            try:
                proxy_enabled = params.get("proxy_enabled", ["false"])[0].lower() == "true"
                proxy_url_val = params.get("proxy_url", ["http://127.0.0.1:10808"])[0].strip()
                concurrent_fragments = max(1, min(16, int(params.get("concurrent_fragments", ["8"])[0])))
                new_settings = {
                    "proxy_enabled": proxy_enabled,
                    "proxy_url": proxy_url_val,
                    "concurrent_fragments": concurrent_fragments,
                }
                save_settings(new_settings)
                logger.info(f"设置已更新: {new_settings}")
                self.send_json({"success": True})
            except (ValueError, KeyError) as e:
                self.send_json({"success": False, "error": str(e)})

        else:
            self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_form(self) -> dict:
        """读取 POST 请求体，支持 application/x-www-form-urlencoded 和 multipart/form-data。"""
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if "multipart/form-data" in content_type:
            # 处理 FormData：简单提取 name/value 对
            result = {}
            try:
                boundary = content_type.split("boundary=")[-1].encode()
                parts = body.split(b"--" + boundary)
                for part in parts:
                    if b"Content-Disposition" not in part:
                        continue
                    header, _, value = part.partition(b"\r\n\r\n")
                    value = value.rstrip(b"\r\n--")
                    name_match = b'name="' in header
                    if name_match:
                        name = header.split(b'name="')[1].split(b'"')[0].decode()
                        result[name] = [value.decode("utf-8", errors="replace")]
            except Exception as e:
                logger.warning(f"解析 multipart 失败: {e}")
            return result
        else:
            return parse_qs(body.decode("utf-8", errors="replace"))

    def send_json(self, obj: object) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


# ── 启动入口 ──────────────────────────────────────────────────────────────────
def main() -> None:
    port = 8080

    # 启动时清理残留的 running 状态（服务器重启后进程已不存在）
    with data_lock:
        data = load_data()
        stale_count = 0
        for task in data["tasks"]:
            if task["status"] == "running":
                task["status"] = "failed"
                task["error"] = "服务器重启，任务中断"
                stale_count += 1
        if stale_count:
            save_data(data)
            logger.warning(f"清理了 {stale_count} 个中断任务（标记为失败）")

    logger.info("=" * 40)
    logger.info(f"yt-dlp Web 管理器")
    logger.info(f"访问地址: http://localhost:{port}")
    logger.info(f"下载目录: {DOWNLOADS_DIR}")

    if not os.path.exists(YTDLP_EXE):
        logger.warning(f"未找到 yt-dlp: {YTDLP_EXE}")
        logger.warning("请运行 install-tools.ps1 下载工具")

    if not os.path.exists(FFMPEG_EXE):
        logger.warning(f"未找到 ffmpeg: {FFMPEG_EXE}（音频转换需要）")

    logger.info("=" * 40)

    os.chdir(BASE_DIR)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("服务已启动，按 Ctrl+C 停止")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务已停止")


if __name__ == "__main__":
    main()