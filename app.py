from flask import Flask, request, jsonify, render_template_string
import sqlite3
from datetime import datetime

app = Flask(__name__)


# Initialize SQLite database table
def init_db():
    conn = sqlite3.connect("impact_logs.db")
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

# HTML & JavaScript Template for Web Dashboard
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ESP32 Impact Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f6f9; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background-color: #007bff; color: white; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .alert { color: #d9534f; font-weight: bold; }
    </style>
</head>
<body>
    <h2>🚨 ESP32 Emergency Impact Dashboard</h2>

    <div class="card">
        <h3>Acceleration Spikes (m/s²)</h3>
        <canvas id="accelChart"></canvas>
    </div>

    <div class="card">
        <h3>Trigger History Log</h3>
        <table>
            <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Dynamic Accel (m/s²)</th>
                <th>Trigger Reason</th>
            </tr>
            {% for log in logs %}
            <tr>
                <td>{{ log[0] }}</td>
                <td>{{ log[1] }}</td>
                <td class="alert">{{ log[2] }} m/s²</td>
                <td>{{ log[3] }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <script>
        const timestamps = {{ timestamps | tojson }};
        const accelData = {{ accel_values | tojson }};

        const ctx = document.getElementById('accelChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: timestamps,
                datasets: [{
                    label: 'Impact Force (m/s²)',
                    data: accelData,
                    borderColor: '#d9534f',
                    backgroundColor: 'rgba(217, 83, 79, 0.2)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'm/s²' } },
                    x: { title: { display: true, text: 'Timestamp' } }
                }
            }
        });
    </script>
</body>
</html>
"""


# Endpoint 1: API for ESP32 to upload impact data
@app.route('/api/log', methods=['POST'])
def log_impact():
    data = request.get_json()
    if not data or 'accel' not in data or 'reason' not in data:
        return jsonify({"status": "error", "message": "Invalid JSON format"}), 400

    accel = data['accel']
    reason = data['reason']
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect("impact_logs.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO logs (timestamp, accel, reason) VALUES (?, ?, ?)", (timestamp, accel, reason))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Impact logged"}), 201


# Endpoint 2: Web Interface accessible via link
@app.route('/')
def dashboard():
    conn = sqlite3.connect("impact_logs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs ORDER BY id DESC")
    logs = cursor.fetchall()
    conn.close()

    # Format data for Chart.js (chronological order for graph)
    chronological_logs = list(reversed(logs))
    timestamps = [log[1] for log in chronological_logs]
    accel_values = [log[2] for log in chronological_logs]

    return render_template_string(HTML_TEMPLATE, logs=logs, timestamps=timestamps, accel_values=accel_values)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
