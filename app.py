import os
import sqlite3
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime

app = Flask(__name__)

# Render provides DATABASE_URL for its managed Postgres; fall back to local SQLite.
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = "impact_logs.db"

# Render's DATABASE_URL sometimes starts with "postgres://", which psycopg2
# rejects — it wants "postgresql://". Normalize it once at startup.
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
    .subtitle { color: #9aa0a6; margin-bottom: 2rem; }
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
    }
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
    <p class="subtitle">Live view of logged impact / acceleration events (auto-refreshes every 3s)</p>
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

    <div class="chart-wrap">
        <canvas id="accelChart" height="90"></canvas>
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
    const ctx = document.getElementById('accelChart').getContext('2d');
    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Acceleration',
                data: [],
                borderColor: '#4f9dff',
                backgroundColor: 'rgba(79,157,255,0.15)',
                tension: 0.25,
                fill: true,
                pointRadius: 3
            }]
        },
        options: {
            responsive: true,
            animation: false,
            scales: {
                x: { ticks: { color: '#9aa0a6' }, grid: { color: '#2a2e37' } },
                y: { ticks: { color: '#9aa0a6' }, grid: { color: '#2a2e37' } }
            },
            plugins: { legend: { labels: { color: '#e6e6e6' } } }
        }
    });

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    async function refresh() {
        try {
            const res = await fetch('/api/logs');
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();

            document.getElementById('statTotal').textContent = data.stats.total_events;
            document.getElementById('statMax').textContent = data.stats.max_accel;
            document.getElementById('statAvg').textContent = data.stats.avg_accel;
            document.getElementById('statLast').textContent = data.stats.last_time;

            chart.data.labels = data.timestamps;
            chart.data.datasets[0].data = data.accel_values;
            chart.update();

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

    refresh();
    setInterval(refresh, 3000);
</script>
</body>
</html>
"""


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
        "logs": list(reversed(logs)),   # newest first, for the table
        "timestamps": timestamps,        # oldest first, for the chart
        "accel_values": accel_values,
        "stats": stats
    })


@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)


if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=debug_mode)
