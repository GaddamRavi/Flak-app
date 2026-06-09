import os
import platform
import shutil
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request


app = Flask(__name__)

APP_NAME = os.getenv("APP_NAME", "OpsPulse")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
STARTED_AT = time.time()
APP_DIRECTORY = Path(__file__).resolve().parent
STORAGE_PATH = Path(os.getenv("APP_STORAGE_PATH", APP_DIRECTORY))

request_lock = threading.Lock()
request_count = 0


def format_bytes(value):
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


def format_duration(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def read_text_file(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def process_memory_bytes():
    status = read_text_file("/proc/self/status")
    if not status:
        return None

    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def cgroup_memory_values():
    paths = (
        ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
        (
            "/sys/fs/cgroup/memory/memory.usage_in_bytes",
            "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        ),
    )

    for usage_path, limit_path in paths:
        usage_text = read_text_file(usage_path)
        limit_text = read_text_file(limit_path)
        if usage_text is None:
            continue

        try:
            usage = int(usage_text)
            limit = None if limit_text in (None, "max") else int(limit_text)
        except ValueError:
            continue

        # Cgroup v1 represents an unlimited value with a very large integer.
        if limit is not None and limit >= 1 << 60:
            limit = None
        return usage, limit

    return None, None


def memory_metrics():
    process_used = process_memory_bytes()
    container_used, container_limit = cgroup_memory_values()
    used = process_used if process_used is not None else container_used

    if used is None:
        return {
            "used_bytes": None,
            "used_percent": None,
            "used": "Unavailable",
            "total": "No limit",
            "container_used": "Unavailable",
            "detail": "Memory metrics unavailable",
            "scope": "unavailable",
        }

    used_percent = None
    if container_limit:
        used_percent = round((used / container_limit) * 100, 1)

    if process_used is not None:
        detail = "Flask process resident memory"
        scope = "process_rss"
    else:
        detail = "Container cgroup memory"
        scope = "container_cgroup"

    if container_limit:
        detail += f" · {format_bytes(container_limit)} container limit"
    else:
        detail += " · no container limit"

    return {
        "used_bytes": used,
        "used_percent": used_percent,
        "used": format_bytes(used),
        "total": format_bytes(container_limit) if container_limit else "No limit",
        "container_used": (
            format_bytes(container_used) if container_used is not None else "Unavailable"
        ),
        "detail": detail,
        "scope": scope,
    }


def directory_size(path):
    total = 0
    pending = [Path(path)]

    while pending:
        current = pending.pop()
        try:
            for entry in os.scandir(current):
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
        except OSError:
            continue

    return total


def disk_metrics():
    app_used = directory_size(STORAGE_PATH)
    filesystem = shutil.disk_usage(STORAGE_PATH)
    return {
        "app_used_bytes": app_used,
        "app_used": format_bytes(app_used),
        "path": str(STORAGE_PATH),
        "filesystem_used_percent": round((filesystem.used / filesystem.total) * 100, 1),
        "filesystem_used": format_bytes(filesystem.used),
        "filesystem_total": format_bytes(filesystem.total),
        "filesystem_free": format_bytes(filesystem.free),
    }


def system_metrics():
    try:
        load_average = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load_average = 0

    return {
        "uptime": format_duration(time.time() - STARTED_AT),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "requests": request_count,
        "load_average": load_average,
        "cpu_count": os.cpu_count() or 1,
        "memory": memory_metrics(),
        "disk": disk_metrics(),
    }


@app.before_request
def track_request():
    global request_count
    with request_lock:
        request_count += 1


@app.get("/healthz")
def health():
    return jsonify(status="healthy", service=APP_NAME, version=APP_VERSION), 200


@app.get("/readyz")
def readiness():
    return jsonify(status="ready", service=APP_NAME), 200


@app.get("/api/status")
def api_status():
    return jsonify(
        status="operational",
        timestamp=datetime.now(timezone.utc).isoformat(),
        application={
            "name": APP_NAME,
            "version": APP_VERSION,
            "environment": ENVIRONMENT,
        },
        runtime={
            "hostname": socket.gethostname(),
            "python": platform.python_version(),
            "platform": platform.system(),
        },
        metrics=system_metrics(),
    )


PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#07101f">
  <title>OpsPulse | Live Operations</title>
  <style>
    :root {
      --bg: #07101f;
      --panel: rgba(17, 31, 54, .76);
      --panel-solid: #101d32;
      --line: rgba(148, 174, 211, .14);
      --text: #edf5ff;
      --muted: #8ea3be;
      --green: #45e6a8;
      --cyan: #54d9ff;
      --violet: #9f8cff;
      --orange: #ffbc66;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 78% -10%, rgba(84, 217, 255, .16), transparent 28%),
        radial-gradient(circle at 8% 35%, rgba(159, 140, 255, .12), transparent 24%),
        var(--bg);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: .25;
      background-image: linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px);
      background-size: 48px 48px;
      mask-image: linear-gradient(to bottom, black, transparent 75%);
    }
    .shell { width: min(1240px, calc(100% - 36px)); margin: auto; position: relative; }
    nav {
      height: 78px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--line);
    }
    .brand { display: flex; align-items: center; gap: 12px; font-size: 17px; font-weight: 750; letter-spacing: -.02em; }
    .logo {
      width: 36px; height: 36px; display: grid; place-items: center; border-radius: 11px;
      background: linear-gradient(135deg, var(--cyan), var(--violet)); color: #07101f;
      box-shadow: 0 0 28px rgba(84, 217, 255, .25);
    }
    .nav-meta { display: flex; align-items: center; gap: 16px; color: var(--muted); font-size: 13px; }
    .live { display: flex; align-items: center; gap: 8px; color: var(--green); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 5px rgba(69, 230, 168, .1); animation: pulse 2s infinite; }
    @keyframes pulse { 50% { box-shadow: 0 0 0 9px rgba(69, 230, 168, 0); } }
    header { padding: 68px 0 42px; display: grid; grid-template-columns: 1.5fr .8fr; align-items: end; gap: 32px; }
    .eyebrow { color: var(--cyan); font-size: 12px; font-weight: 750; text-transform: uppercase; letter-spacing: .18em; }
    h1 { margin: 13px 0 16px; max-width: 720px; font-size: clamp(42px, 7vw, 76px); line-height: .98; letter-spacing: -.065em; }
    .gradient { background: linear-gradient(90deg, var(--cyan), var(--violet)); -webkit-background-clip: text; color: transparent; }
    .lead { max-width: 600px; margin: 0; color: var(--muted); font-size: 16px; line-height: 1.7; }
    .hero-status { padding: 19px; border: 1px solid rgba(69, 230, 168, .25); background: rgba(69, 230, 168, .06); border-radius: 18px; }
    .hero-status strong { display: block; font-size: 18px; margin-bottom: 5px; }
    .hero-status span { color: var(--muted); font-size: 13px; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; padding-bottom: 48px; }
    .card {
      border: 1px solid var(--line); border-radius: 20px; padding: 22px;
      background: var(--panel); backdrop-filter: blur(16px); box-shadow: 0 18px 60px rgba(0, 0, 0, .15);
    }
    .metric { grid-column: span 3; min-height: 155px; display: flex; flex-direction: column; justify-content: space-between; }
    .metric-top { display: flex; justify-content: space-between; align-items: center; color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; }
    .icon { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; background: rgba(84, 217, 255, .08); color: var(--cyan); font-size: 15px; }
    .value { margin: 18px 0 4px; font-size: 31px; font-weight: 760; letter-spacing: -.045em; }
    .sub { color: var(--muted); font-size: 12px; }
    .wide { grid-column: span 8; }
    .side { grid-column: span 4; }
    .card-title { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
    .card-title h2 { margin: 0 0 5px; font-size: 16px; letter-spacing: -.02em; }
    .card-title p { margin: 0; color: var(--muted); font-size: 12px; }
    .badge { padding: 6px 10px; border: 1px solid var(--line); border-radius: 99px; color: var(--muted); font-size: 11px; }
    .service { display: grid; grid-template-columns: 1.3fr 1fr 110px; gap: 16px; align-items: center; padding: 17px 0; border-top: 1px solid var(--line); }
    .service:first-of-type { border-top: 0; }
    .service-name { display: flex; align-items: center; gap: 11px; font-size: 13px; font-weight: 650; }
    .service-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 12px rgba(69, 230, 168, .6); }
    .service-info { color: var(--muted); font-size: 12px; }
    .bar { height: 6px; border-radius: 99px; overflow: hidden; background: rgba(148, 174, 211, .1); }
    .bar span { display: block; width: 0; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--cyan), var(--violet)); transition: width .6s ease; }
    .runtime { display: grid; gap: 12px; }
    .runtime-row { display: flex; justify-content: space-between; gap: 20px; padding: 14px 0; border-bottom: 1px solid var(--line); font-size: 12px; }
    .runtime-row:last-child { border: 0; }
    .runtime-row span { color: var(--muted); }
    .runtime-row strong { max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    footer { padding: 6px 0 32px; color: var(--muted); font-size: 11px; text-align: center; }
    @media (max-width: 900px) {
      header { grid-template-columns: 1fr; padding-top: 48px; }
      .metric { grid-column: span 6; }
      .wide, .side { grid-column: span 12; }
    }
    @media (max-width: 580px) {
      .shell { width: min(100% - 24px, 1240px); }
      nav { height: 66px; }
      .nav-meta > span:not(.live) { display: none; }
      header { padding: 38px 0 28px; }
      h1 { font-size: 45px; }
      .metric { grid-column: span 12; min-height: 132px; }
      .service { grid-template-columns: 1fr; gap: 8px; }
      .card { padding: 18px; border-radius: 16px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <nav>
      <div class="brand"><div class="logo">O</div> OpsPulse</div>
      <div class="nav-meta"><span id="clock">--:--:-- UTC</span><span class="live"><i class="dot"></i> Live telemetry</span></div>
    </nav>

    <header>
      <div>
        <div class="eyebrow">Infrastructure intelligence</div>
        <h1>Everything is <span class="gradient">operational.</span></h1>
        <p class="lead">A lightweight command center for your containerized Flask workload, with real-time runtime and system telemetry.</p>
      </div>
      <div class="hero-status">
        <strong>All systems healthy</strong>
        <span id="lastUpdate">Connecting to telemetry...</span>
      </div>
    </header>

    <main class="grid">
      <article class="card metric">
        <div class="metric-top">Uptime <i class="icon">↗</i></div>
        <div><div class="value" id="uptime">--</div><div class="sub">Since current instance started</div></div>
      </article>
      <article class="card metric">
        <div class="metric-top">Requests <i class="icon">#</i></div>
        <div><div class="value" id="requests">--</div><div class="sub">Handled by this instance</div></div>
      </article>
      <article class="card metric">
        <div class="metric-top">App Memory <i class="icon">M</i></div>
        <div><div class="value" id="memory">--</div><div class="sub" id="memorySub">Flask process resident memory</div></div>
      </article>
      <article class="card metric">
        <div class="metric-top">App Storage <i class="icon">D</i></div>
        <div><div class="value" id="disk">--</div><div class="sub" id="diskSub">Files stored in the application directory</div></div>
      </article>

      <section class="card wide">
        <div class="card-title">
          <div><h2>Service overview</h2><p>Live checks from the current application instance</p></div>
          <span class="badge">Auto-refresh · 3s</span>
        </div>
        <div class="service">
          <div class="service-name"><i class="service-dot"></i> HTTP API</div>
          <div class="service-info">Accepting requests</div>
          <div class="bar"><span style="width:100%"></span></div>
        </div>
        <div class="service">
          <div class="service-name"><i class="service-dot"></i> Python runtime</div>
          <div class="service-info" id="pythonService">Loading...</div>
          <div class="bar"><span id="loadBar"></span></div>
        </div>
        <div class="service">
          <div class="service-name"><i class="service-dot"></i> Storage</div>
          <div class="service-info" id="storageService">Loading...</div>
          <div class="bar"><span id="diskBar"></span></div>
        </div>
      </section>

      <aside class="card side">
        <div class="card-title">
          <div><h2>Deployment details</h2><p>Current workload identity</p></div>
        </div>
        <div class="runtime">
          <div class="runtime-row"><span>Application</span><strong id="appName">--</strong></div>
          <div class="runtime-row"><span>Version</span><strong id="version">--</strong></div>
          <div class="runtime-row"><span>Environment</span><strong id="environment">--</strong></div>
          <div class="runtime-row"><span>Hostname</span><strong id="hostname">--</strong></div>
          <div class="runtime-row"><span>Platform</span><strong id="platform">--</strong></div>
          <div class="runtime-row"><span>CPU cores</span><strong id="cores">--</strong></div>
        </div>
      </aside>
    </main>
    <footer>OpsPulse · Built for containers, Kubernetes, and calm operations.</footer>
  </div>

  <script>
    const byId = (id) => document.getElementById(id);
    const text = (id, value) => byId(id).textContent = value;

    function tickClock() {
      text("clock", new Date().toLocaleTimeString("en-GB", { timeZone: "UTC" }) + " UTC");
    }

    async function refresh() {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        if (!response.ok) throw new Error("Telemetry unavailable");
        const data = await response.json();
        const m = data.metrics;

        text("uptime", m.uptime);
        text("requests", Number(m.requests).toLocaleString());
        text("memory", m.memory.used);
        text("memorySub", m.memory.detail);
        text("disk", m.disk.app_used);
        text("diskSub", m.disk.filesystem_free + " free on container filesystem");
        text("pythonService", "Python " + data.runtime.python + " · load " + m.load_average);
        text("storageService", m.disk.filesystem_used_percent + "% filesystem utilized");
        byId("loadBar").style.width = Math.min(100, (m.load_average / Math.max(m.cpu_count, 1)) * 100) + "%";
        byId("diskBar").style.width = m.disk.filesystem_used_percent + "%";
        text("appName", data.application.name);
        text("version", data.application.version);
        text("environment", data.application.environment);
        text("hostname", data.runtime.hostname);
        text("platform", data.runtime.platform);
        text("cores", m.cpu_count);
        text("lastUpdate", "Last verified " + new Date(data.timestamp).toLocaleTimeString());
      } catch (error) {
        text("lastUpdate", error.message + " · retrying automatically");
      }
    }

    tickClock();
    refresh();
    setInterval(tickClock, 1000);
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""


@app.get("/")
def home():
    return render_template_string(PAGE)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="not_found", message="The requested endpoint does not exist."), 404
    return (
        "<h1 style='font-family:system-ui'>404</h1>"
        "<p style='font-family:system-ui'>This page does not exist. "
        "<a href='/'>Return to OpsPulse</a>.</p>",
        404,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
