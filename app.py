from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_PATH = "impact_logs.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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
</style>
</head>
<body>
    <h1>Impact Log Dashboard</h1>
    <p class="subtitle">Live view of logged impact / acceleration events</p>

    <div class="stats">
        <div class="card">
            <div class="label">Total Events</div>
            <div class="value">{{ stats.total_events }}</div>
        </div>
        <div class="card">
            <div class="label">Max Accel</div>
            <div class="value">{{ stats.max_accel }}</div>
        </div>
        <div class="card">
            <div class="label">Avg Accel</div>
            <div class="value">{{ stats.avg_accel }}</div>
        </div>
        <div class="card">
            <div class="label">Last Event</div>
            <div class="value" style="font-size:1.1rem;">{{ stats.last_time }}</div>
        </div>
    </div>

    <div class="chart-wrap">
        <canvas id="accelChart" height="90"></canvas>
    </div>

    {% if logs %}
    <table>
        <thead>
            <tr><th>ID</th><th>Timestamp</th><th>Accel</th><th>Reason</th></tr>
        </thead>
        <tbody>
        {% for log in logs %}
            <tr>
                <td>{{ log[0] }}</td>
                <td>{{ log[1] }}</td>
                <td>{{ log[2] }}</td>
                <td>{{ log[3] }}</td>
            </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}
        <div class="empty">No events logged yet.</div>
    {% endif %}

<script>
    const ctx = document.getElementById('accelChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: {{ timestamps | tojson }},
            datasets: [{
                label: 'Acceleration',
                data: {{ accel_values | tojson }},
                borderColor: '#4f9dff',
                backgroundColor: 'rgba(79,157,255,0.15)',
                tension: 0.25,
                fill: true,
                pointRadius: 3
            }]
        },
        options: {
            responsive: true,
            scales: {
                x: { ticks: { color: '#9aa0a6' }, grid: { color: '#2a2e37' } },
                y: { ticks: { color: '#9aa0a6' }, grid: { color: '#2a2e37' } }
            },
            plugins: { legend: { labels: { color: '#e6e6e6' } } }
        }
    });
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

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs (timestamp, accel, reason) VALUES (?, ?, ?)",
        (timestamp, accel, reason)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Impact logged"}), 201


@app.route('/')
def dashboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs ORDER BY id ASC")
    logs = cursor.fetchall()
    conn.close()

    timestamps = [log[1] for log in logs]
    accel_values = [log[2] for log in logs]

    total_events = len(logs)
    max_accel = max(accel_values) if accel_values else 0.0
    avg_accel = round(sum(accel_values) / total_events, 2) if total_events > 0 else 0.0
    last_time = logs[-1][1] if logs else "No Events"

    stats = {
        "total_events": total_events,
        "max_accel": max_accel,
        "avg_accel": avg_accel,
        "last_time": last_time
    }

    # Table should read newest-first; chart should read oldest-first (left to right).
    return render_template_string(
        HTML_TEMPLATE,
        logs=list(reversed(logs)),
        timestamps=timestamps,
        accel_values=accel_values,
        stats=stats
    )


if __name__ == '__main__':
    # NOTE: debug=True enables Werkzeug's interactive debugger, which allows
    # arbitrary remote code execution if this is ever exposed off localhost.
    # Fine for local dev, turn it off (or use an env var) before deploying anywhere.
    app.run(host='0.0.0.0', port=5000, debug=True)
