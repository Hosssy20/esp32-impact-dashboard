import os
import sqlite3
import threading
from collections import deque
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Persistent storage (trigger events only — Postgres on Render, SQLite locally)
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = "impact_logs.db"

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def get_db_connection():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(50) NOT NULL,
                accel REAL NOT NULL,
                reason TEXT NOT NULL
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                accel REAL NOT NULL,
                reason TEXT NOT NULL
            )
        ''')
    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------------------------------
# In-memory live state (NOT persisted — this is the fast, ephemeral stream)
# ---------------------------------------------------------------------------
LIVE_BUFFER_MAX = 300          # how many live points the chart keeps on screen
STABILITY_THRESHOLD = float(os.environ.get("STABILITY_THRESHOLD", 2.0))
STABILITY_SAMPLES = int(os.environ.get("STABILITY_SAMPLES", 5))  # consecutive calm readings needed to resume

live_lock = threading.Lock()
live_state = {
    "status": "stable",       # "stable" or "triggered"
    "reason": None,
    "stable_streak": 0,
    "buffer": deque(maxlen=LIVE_BUFFER_MAX),  # each item: {"t": "...", "accel": float}
}


@app.route('/api/live', methods=['POST'])
def post_live():
    """High-frequency endpoint: device posts its current accel reading here.
    Not written to disk — only kept in memory for the live chart."""
    data = request.get_json(silent=True)
    if not data or 'accel' not in data:
        return jsonify({"status": "error", "message": "Missing 'accel'"}), 400

    try:
        accel = float(data['accel'])
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "'accel' must be a number"}), 400

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    with live_lock:
        if live_state["status"] == "stable":
            live_state["buffer"].append({"t": now, "accel": accel})
        else:
            # Frozen: don't extend the visible line, just watch for calm readings.
            if abs(accel) < STABILITY_THRESHOLD:
                live_state["stable_streak"] += 1
                if live_state["stable_streak"] >= STABILITY_SAMPLES:
                    live_state["status"] = "stable"
                    live_state["reason"] = None
                    live_state["stable_streak"] = 0
                    live_state["buffer"].append({"t": now, "accel": accel})  # resume the line here
            else:
                live_state["stable_streak"] = 0

        status_snapshot = live_state["status"]

    return jsonify({"status": "ok", "system_state": status_snapshot}), 200


@app.route('/api/live', methods=['GET'])
def get_live():
    with live_lock:
        return jsonify({
            "status": live_state["status"],
            "reason": live_state["reason"],
            "points": list(live_state["buffer"]),
        })


# ---------------------------------------------------------------------------
# Trigger events (persisted, unchanged behavior + they now freeze the live line)
# ---------------------------------------------------------------------------
@app.route('/api/log', methods=['POST'])
def log_impact():
    data = request.get_json(silent=True)
    if not data or 'accel' not in data or 'reason' not in data:
        return jsonify({"status": "error", "message": "Invalid JSON format"}), 400

    try:
        accel = float(data['accel'])
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "'accel' must be a number"}), 400

    reason = str(data['reason']).strip()
    if not reason:
        return jsonify({"status": "error", "message": "'reason' cannot be empty"}), 400

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholder = "%s" if DATABASE_URL else "?"
        cursor.execute(
            f"INSERT INTO logs (timestamp, accel, reason) VALUES "
            f"({placeholder}, {placeholder}, {placeholder})",
            (timestamp, accel, reason)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database error: {e}"}), 500

    # Freeze the live line and mark the system as triggered.
    with live_lock:
        live_state["status"] = "triggered"
        live_state["reason"] = reason
        live_state["stable_streak"] = 0

    return jsonify({"status": "success", "message": "Impact logged"}), 201


@app.route('/api/logs', methods=['GET'])
def get_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, timestamp, accel, reason FROM logs ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    logs = [{"id": row[0], "timestamp": row[1], "accel": row[2], "reason": row[3]} for row in rows]
    timestamps = [log["timestamp"] for log in logs]
    accel_values = [log["accel"] for log in logs]

    total_events = len(logs)
    max_accel = max(accel_values) if accel_values else 0.0
    avg_accel = round(sum(accel_values) / total_events, 2) if total_events > 0 else 0.0
    last_time = logs[-1]["timestamp"] if logs else "No Events"

    stats = {
        "total_events": total_events,
        "max_accel": max_accel,
        "avg_accel": avg_accel,
        "last_time": last_time
    }

    return jsonify({
        "logs": list(reversed(logs)),
        "timestamps": timestamps,
        "accel_values": accel_values,
        "stats": stats
    })


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Impact Log Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0f1115;
        color: #e6e6e6;
        margin: 0;
        padding: 2rem;
    }
    h1 { margin-bottom: 0.25rem; }
    h2 { font-size: 1.1rem; color: #cfd3d8; margin: 0 0 0.75rem; }
    .subtitle { color: #9aa0a6; margin-bottom: 1.5rem; }
    .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 1rem;
        margin-bottom: 2rem;
    }
    .card {
        background: #1a1d24;
        border: 1px solid #2a2e37;
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }
    .card .label { font-size: 0.8rem; color: #9aa0a6; text-transform: uppercase; letter-spacing: 0.04em; }
    .card .value { font-size: 1.6rem; font-weight: 600; margin-top: 0.25rem; }
    .chart-wrap {
        background: #1a1d24;
        border: 1px solid #2a2e37;
        border-radius: 10px;
        padding: 1.25rem;
        margin-bottom: 2rem;
        position: relative;
    }
    .live-banner {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.8rem;
        padding: 0.35rem 0.75rem;
        border-radius: 999px;
        margin-bottom: 1rem;
        background: #16351f;
        color: #4ade80;
        border: 1px solid #1e4a2a;
    }
    .live-banner.triggered {
        background: #3a1717;
        color: #f87171;
        border-color: #5a2020;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    table { width: 100%; border-collapse: collapse; background: #1a1d24; border-radius: 10px; overflow: hidden; }
    th, td { text-align: left; padding: 0.6rem 1rem; border-bottom: 1px solid #2a2e37; font-size: 0.9rem; }
    th { color: #9aa0a6; font-weight: 500; text-transform: uppercase; font-size: 0.75rem; }
    tr:last-child td { border-bottom: none; }
    .empty { color: #9aa0a6; padding: 1rem; text-align: center; }
    .status { font-size: 0.75rem; color: #666; margin-bottom: 1rem; }
</style>
</head>
<body>
    <h1>Impact Log Dashboard</h1>
    <p class="subtitle">Live acceleration feed + persisted trigger events</p>

    <h2>Live Acceleration</h2>
    <div id="liveBanner" class="live-banner">
        <span class="dot"></span>
        <span id="liveBannerText">Stable</span>
    </div>
    <div class="chart-wrap">
        <canvas id="liveChart" height="80"></canvas>
    </div>

    <h2>Trigger Event History</h2>
    <p class="status" id="statusLine">Loading...</p>

    <div class="stats">
        <div class="card">
            <div class="label">Total Events</div>
            <div class="value" id="statTotal">0</div>
        </div>
        <div class="card">
            <div class="label">Max Accel</div>
            <div class="value" id="statMax">0.0</div>
        </div>
        <div class="card">
            <div class="label">Avg Accel</div>
            <div class="value" id="statAvg">0.0</div>
        </div>
        <div class="card">
            <div class="label">Last Event</div>
            <div class="value" id="statLast" style="font-size:1.1rem;">No Events</div>
        </div>
    </div>

    <table>
        <thead>
            <tr><th>ID</th><th>Timestamp</th><th>Accel</th><th>Reason</th></tr>
        </thead>
        <tbody id="logsBody">
            <tr><td colspan="4" class="empty">Loading events...</td></tr>
        </tbody>
    </table>

<script>
    const GREEN = '#22c55e';
    const RED = '#ef4444';

    // ---- Live chart (green = stable & flowing, red = frozen/triggered) ----
    const liveCtx = document.getElementById('liveChart').getContext('2d');
    const liveChart = new Chart(liveCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Live Acceleration',
                data: [],
                borderColor: GREEN,
                backgroundColor: 'rgba(34,197,94,0.12)',
                tension: 0.2,
                fill: true,
                pointRadius: 0,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            animation: false,
            scales: {
                x: { ticks: { color: '#9aa0a6', maxTicksLimit: 8 }, grid: { color: '#2a2e37' } },
                y: { ticks: { color: '#9aa0a6' }, grid: { color: '#2a2e37' } }
            },
            plugins: { legend: { display: false } }
        }
    });

    async function refreshLive() {
        try {
            const res = await fetch('/api/live');
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();

            const triggered = data.status === 'triggered';
            const banner = document.getElementById('liveBanner');
            const bannerText = document.getElementById('liveBannerText');
            banner.classList.toggle('triggered', triggered);
            bannerText.textContent = triggered
                ? `TRIGGERED — ${data.reason || 'unknown reason'} — waiting for stability`
                : 'Stable';

            liveChart.data.labels = data.points.map(p => p.t);
            liveChart.data.datasets[0].data = data.points.map(p => p.accel);
            const color = triggered ? RED : GREEN;
            liveChart.data.datasets[0].borderColor = color;
            liveChart.data.datasets[0].backgroundColor = triggered
                ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)';
            liveChart.update();
        } catch (err) {
            // stay quiet on transient live-feed errors, the trigger table still updates
        }
    }

    // ---- Trigger event history (unchanged, slower poll) ----
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    async function refreshLogs() {
        try {
            const res = await fetch('/api/logs');
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();

            document.getElementById('statTotal').textContent = data.stats.total_events;
            document.getElementById('statMax').textContent = data.stats.max_accel;
            document.getElementById('statAvg').textContent = data.stats.avg_accel;
            document.getElementById('statLast').textContent = data.stats.last_time;

            const body = document.getElementById('logsBody');
            if (data.logs.length === 0) {
                body.innerHTML = '<tr><td colspan="4" class="empty">No events logged yet.</td></tr>';
            } else {
                body.innerHTML = data.logs.map(log =>
                    `<tr><td>${log.id}</td><td>${escapeHtml(log.timestamp)}</td><td>${log.accel}</td><td>${escapeHtml(log.reason)}</td></tr>`
                ).join('');
            }

            document.getElementById('statusLine').textContent =
                'Last updated: ' + new Date().toLocaleTimeString();
        } catch (err) {
            document.getElementById('statusLine').textContent =
                'Update failed (' + err.message + '), retrying...';
        }
    }

    refreshLive();
    refreshLogs();
    setInterval(refreshLive, 500);   // fast poll for the live feed
    setInterval(refreshLogs, 3000);  // slower poll for the historical table
</script>
</body>
</html>
"""


@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)


if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=debug_mode)
