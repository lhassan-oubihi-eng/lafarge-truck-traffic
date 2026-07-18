"""
Lafarge - Truck Traffic Management System
-------------------------------------------------
Application de gestion et supervision du trafic des camions sur site.
Expose :
  - GET  /                 : Dashboard HTML (vue opérationnelle)
  - GET  /metrics          : Métriques au format Prometheus
  - GET  /api/trucks       : Liste JSON des camions suivis (état courant)
  - POST /api/trucks/enter : Enregistre l'entrée d'un camion sur site
  - POST /api/trucks/exit  : Enregistre la sortie d'un camion du site
  - GET  /healthz          : Health check utilisé par le Target Group AWS
"""

import json
import os
import random
import time
import uuid
import logging
from datetime import datetime, timezone
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import BackgroundTasks, FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# S3 Service (LocalStack) – lazy import to avoid boto3 requirement at
# module load time (important for unit tests running without boto3).
# Works both inside the Docker container (services.s3_service) and
# from the host / test runner (app.services.s3_service).
# --------------------------------------------------------------------------
def _get_s3_service():
    try:
        from services.s3_service import s3_service  # Docker container

        return s3_service
    except ModuleNotFoundError:
        from app.services.s3_service import s3_service  # Host / CI

        return s3_service


# --------------------------------------------------------------------------
# Monitoring Service – lazy import for the same reason as S3 above.
# Provides platform health metrics (CPU, memory, instances, S3, latency).
# --------------------------------------------------------------------------
def _get_monitoring_service():
    try:
        from services.monitoring import monitoring_service  # Docker

        return monitoring_service
    except ModuleNotFoundError:
        from app.services.monitoring import monitoring_service  # Host / CI

        return monitoring_service


APP_NAME = "lafarge-truck-traffic"
APP_VERSION = "1.0.0"

app = FastAPI(title="Lafarge Truck Traffic Management", version=APP_VERSION)

# --------------------------------------------------------------------------
# Rate Limiting Configuration
# --------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --------------------------------------------------------------------------
# AWS Secrets Manager Integration
# --------------------------------------------------------------------------
def get_secret_safely(secret_name: str) -> dict:
    """Retrieve a secret from AWS Secrets Manager or LocalStack with fallback."""
    region_name = os.getenv("AWS_REGION", "us-east-1")
    client_kwargs = {"region_name": region_name}

    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url

    try:
        session = boto3.session.Session()
        client = session.client("secretsmanager", **client_kwargs)
        response = client.get_secret_value(SecretId=secret_name)
        secret_string = response.get("SecretString", "{}")
        return json.loads(secret_string)
    except (BotoCoreError, ClientError) as e:
        logger.warning(
            f"Could not retrieve secret '{secret_name}': {e}. Using local fallback environment variables."
        )
        return {}


@lru_cache(maxsize=1)
def load_runtime_secrets() -> dict:
    """Load and resolve runtime secrets from AWS Secrets Manager or environment.

    Raises:
        RuntimeError: If a required environment variable is missing.
    """
    db_secret_name = os.getenv("DB_SECRET_NAME", "lafarge/truck-traffic/local/db")
    aws_secret_name = os.getenv("AWS_SECRET_NAME", "lafarge/truck-traffic/local/aws")

    db_secret = get_secret_safely(db_secret_name)
    aws_secret = get_secret_safely(aws_secret_name)

    def _require(key: str, source: dict | None = None) -> str:
        """Get value from source dict or env, raise if missing."""
        if source and key in source:
            return source[key]
        value = os.getenv(key)
        if value is None:
            raise RuntimeError(f"Required environment variable '{key}' is not set")
        return value

    resolved = {
        "DB_HOST": _require("DB_HOST", db_secret),
        "DB_PORT": _require("DB_PORT", db_secret),
        "DB_NAME": _require("DB_NAME", db_secret),
        "DB_USER": _require("DB_USER", db_secret),
        "DB_PASSWORD": _require("DB_PASSWORD", db_secret),
        "AWS_ACCESS_KEY_ID": _require("AWS_ACCESS_KEY_ID", aws_secret),
        "AWS_SECRET_ACCESS_KEY": _require("AWS_SECRET_ACCESS_KEY", aws_secret),
    }

    for key, value in resolved.items():
        os.environ[key] = value

    return resolved


@app.on_event("startup")
async def startup_event():
    """Initialize runtime configuration on application startup."""
    load_runtime_secrets()
    # Restore Prometheus metrics from S3 so they survive a container restart.
    try:
        s3 = _get_s3_service()
        logs = s3.list_truck_logs()
        entry_count = sum(1 for t in logs if t.get("event") == "truck_entry")
        exit_count = sum(1 for t in logs if t.get("event") == "truck_exit")
        on_site = entry_count - exit_count
        if on_site < 0:
            on_site = 0
        TRUCKS_ON_SITE.set(on_site)
        TRUCKS_PROCESSED_TOTAL.labels(operation="entry")._inc(entry_count)
        TRUCKS_PROCESSED_TOTAL.labels(operation="exit")._inc(exit_count)
        logger.info(
            "Restored metrics from S3: %d entries, %d exits, %d on site",
            entry_count,
            exit_count,
            on_site,
        )
    except Exception:
        logger.info(
            "S3 not available at startup; metrics start at zero (expected in CI)."
        )
    logger.info(f"{APP_NAME} v{APP_VERSION} started successfully")


# --------------------------------------------------------------------------
# Métriques Prometheus
# --------------------------------------------------------------------------

# Nombre total de requêtes HTTP reçues, ventilé par méthode / route / statut
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Nombre total de requêtes HTTP traitées par l'application",
    ["method", "endpoint", "http_status"],
)

# Distribution de la latence des requêtes (utile pour les SLO)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Durée de traitement des requêtes HTTP (secondes)",
    ["method", "endpoint"],
)

# Métier : nombre total de camions ayant été traités (entrée + sortie confirmée)
TRUCKS_PROCESSED_TOTAL = Counter(
    "trucks_processed_total",
    "Nombre total de camions dont le passage a été traité (entrée ou sortie)",
    ["operation"],  # "entry" ou "exit"
)

# Métier : jauge du nombre de camions actuellement présents sur le site
TRUCKS_ON_SITE = Gauge(
    "trucks_on_site",
    "Nombre de camions actuellement présents sur le site Lafarge",
)

# Métier : temps moyen d'attente simulé au poste de pesée (secondes)
TRUCK_WEIGHING_DURATION_SECONDS = Histogram(
    "truck_weighing_duration_seconds",
    "Durée du passage au pont-bascule (secondes)",
)

# --------------------------------------------------------------------------
# État applicatif en mémoire (à remplacer par une vraie base de données
# en production - PostgreSQL / DynamoDB selon le besoin de scalabilité)
# --------------------------------------------------------------------------
TRUCKS_REGISTRY: dict[str, dict] = {}


# --------------------------------------------------------------------------
# Middleware : instrumentation Prometheus automatique sur toutes les routes
# --------------------------------------------------------------------------
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    response: Response = await call_next(request)
    duration = time.perf_counter() - start_time

    endpoint = request.url.path
    HTTP_REQUESTS_TOTAL.labels(
        method=request.method,
        endpoint=endpoint,
        http_status=response.status_code,
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=request.method,
        endpoint=endpoint,
    ).observe(duration)

    return response


# --------------------------------------------------------------------------
# Route : Dashboard HTML — Operations Control Center
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    s3 = _get_s3_service()
    monitoring = _get_monitoring_service()

    try:
        logs = s3.list_truck_logs()
    except Exception:
        logs = []

    # Fallback to in-memory registry if S3 is unavailable (e.g., in tests)
    if not logs and TRUCKS_REGISTRY:
        for truck_id, truck in TRUCKS_REGISTRY.items():
            event = "truck_entry" if truck["status"] == "on_site" else "truck_exit"
            logs.append(
                {
                    "truck_id": truck_id,
                    "license_plate": truck["plate"],
                    "event": event,
                    "event_time": truck["entry_time"],
                    "exit_time": truck.get("exit_time"),
                }
            )

    # --- Business metrics ---
    trucks_count = len(logs)
    trucks_on_site_count = sum(
        1 for t in logs if t.get("event") == "truck_entry" and not t.get("exit_time")
    )
    entries_today = sum(1 for t in logs if t.get("event") == "truck_entry")
    exits_today = sum(1 for t in logs if t.get("event") == "truck_exit")

    # --- Platform metrics ---
    system = monitoring.get_system_status()
    traffic_history = monitoring.get_traffic_history()

    # Health colour classes for progress bars
    def _health_class(val):
        if val > 85:
            return "danger"
        if val > 65:
            return "warning"
        return "green"

    cpu_class = _health_class(system["cpu_usage_percent"])
    mem_class = _health_class(system["memory_usage_percent"])
    overall_color = (
        "var(--success)"
        if system["overall_status"] == "healthy"
        else (
            "var(--warning)"
            if system["overall_status"] == "degraded"
            else "var(--danger)"
        )
    )

    # --- Recent movements table rows ---
    trucks_rows = ""
    for entry in logs[-10:][::-1]:
        truck_id = entry.get("truck_id", "N/A")
        plate = entry.get("license_plate", "N/A")
        event = entry.get("event", "unknown")
        event_time = entry.get("event_time", "N/A")
        status_label = "On Site" if event == "truck_entry" else "Exited"
        status_class = "status-onsite" if event == "truck_entry" else "status-exited"
        trucks_rows += f"""
        <tr>
            <td><span class="mono">{truck_id[:8]}</span></td>
            <td>{plate}</td>
            <td><span class="badge {status_class}">{status_label}</span></td>
            <td class="mono">{event_time}</td>
        </tr>"""

    if not trucks_rows:
        trucks_rows = (
            "<tr><td colspan='4' class='empty'>No trucks recorded yet</td></tr>"
        )

    # --- Traffic history JSON for Chart.js ---
    import json as _json

    traffic_json = _json.dumps(traffic_history)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lafarge Site Operations Platform | Control Center</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>
        /* ============================================================
           DESIGN SYSTEM — Enterprise dark theme (Grafana-style)
           ============================================================ */
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --bg-card-hover: #253248;
            --border: #2d3a4e;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent: #EE7203;
            --accent-glow: rgba(238,114,3,0.15);
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --lafarge-blue: #003057;
            --radius: 12px;
            --shadow: 0 4px 24px rgba(0,0,0,0.3);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.5;
        }}

        /* --- Header --- */
        .header {{
            background: linear-gradient(135deg, #0a1628 0%, #1a2332 100%);
            border-bottom: 1px solid var(--border);
            padding: 16px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header-brand {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .header-brand .logo {{
            width: 36px; height: 36px;
            background: var(--accent);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800; font-size: 18px;
            color: #0f172a;
        }}
        .header-brand h1 {{
            font-size: 18px; font-weight: 600;
            letter-spacing: 0.3px;
        }}
        .header-brand h1 span {{
            color: var(--accent);
        }}
        .header-brand .subtitle {{
            font-size: 12px; color: var(--text-muted);
            margin-top: -2px;
        }}
        .header-status {{
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 13px;
        }}
        .status-indicator {{
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: 20px;
            background: rgba(34,197,94,0.1);
            border: 1px solid rgba(34,197,94,0.25);
        }}
        .status-indicator .dot {{
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.4; }}
        }}
        .header-meta {{
            color: var(--text-muted);
            font-size: 12px;
        }}

        /* --- Container --- */
        .container {{
            max-width: 1440px;
            margin: 0 auto;
            padding: 24px 32px;
        }}

        /* --- Section title --- */
        .section-title {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-secondary);
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        .section-title .icon {{ font-size: 16px; }}

        /* --- Metric cards grid --- */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .metric-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        .metric-card:hover {{
            border-color: var(--accent);
            box-shadow: 0 0 20px var(--accent-glow);
        }}
        .metric-card .label {{
            font-size: 11px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            margin-bottom: 6px;
        }}
        .metric-card .value {{
            font-size: 28px;
            font-weight: 700;
            color: var(--text-primary);
            line-height: 1.1;
        }}
        .metric-card .value .unit {{
            font-size: 14px;
            font-weight: 400;
            color: var(--text-secondary);
            margin-left: 4px;
        }}
        .metric-card .sub {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
        }}
        .metric-card.accent {{
            border-left: 3px solid var(--accent);
        }}
        .metric-card.green {{ border-left: 3px solid var(--success); }}
        .metric-card.blue {{ border-left: 3px solid #3b82f6; }}

        /* --- Progress bar (for CPU / Memory) --- */
        .progress-bar {{
            width: 100%;
            height: 6px;
            background: #2d3a4e;
            border-radius: 4px;
            margin-top: 10px;
            overflow: hidden;
        }}
        .progress-bar .fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.8s ease;
        }}
        .fill-green {{ background: var(--success); }}
        .fill-warning {{ background: var(--warning); }}
        .fill-danger {{ background: var(--danger); }}
        .fill-accent {{ background: var(--accent); }}

        /* --- Chart container --- */
        .chart-wrapper {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            margin-bottom: 32px;
        }}
        .chart-wrapper canvas {{
            max-height: 260px;
        }}

        /* --- Table --- */
        .table-wrapper {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            margin-bottom: 32px;
        }}
        .table-wrapper table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .table-wrapper th,
        .table-wrapper td {{
            padding: 12px 20px;
            text-align: left;
            font-size: 13px;
        }}
        .table-wrapper th {{
            background: #0f172a;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            font-size: 11px;
            border-bottom: 1px solid var(--border);
        }}
        .table-wrapper td {{
            border-bottom: 1px solid rgba(45,58,78,0.5);
            color: var(--text-primary);
        }}
        .table-wrapper tr:last-child td {{ border-bottom: none; }}
        .table-wrapper tr:hover td {{
            background: rgba(238,114,3,0.04);
        }}

        /* --- Badges --- */
        .badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }}
        .badge.status-onsite {{
            background: rgba(34,197,94,0.12);
            color: var(--success);
        }}
        .badge.status-exited {{
            background: rgba(100,116,139,0.15);
            color: var(--text-muted);
        }}
        .mono {{ font-family: 'JetBrains Mono', 'Cascadia Code', monospace; font-size: 12px; }}
        .empty {{ text-align: center; color: var(--text-muted); padding: 32px; font-size: 13px; }}

        /* --- Footer --- */
        .footer {{
            text-align: center;
            padding: 20px;
            color: var(--text-muted);
            font-size: 11px;
            border-top: 1px solid var(--border);
            margin-top: 16px;
        }}

        /* --- Responsive --- */
        @media (max-width: 768px) {{
            .header {{ padding: 12px 16px; }}
            .header-status {{ width: 100%; justify-content: flex-start; }}
            .container {{ padding: 16px; }}
            .metrics-grid {{ grid-template-columns: repeat(2, 1fr); gap: 12px; }}
            .metric-card .value {{ font-size: 22px; }}
            .table-wrapper th,
            .table-wrapper td {{ padding: 10px 12px; font-size: 12px; }}
        }}
        @media (max-width: 480px) {{
            .metrics-grid {{ grid-template-columns: 1fr; }}
        }}

        /* --- Last-updated timestamp --- */
        .last-updated {{
            position: fixed;
            bottom: 16px;
            right: 24px;
            font-size: 11px;
            color: var(--text-muted);
            background: rgba(15,23,42,0.85);
            padding: 6px 14px;
            border-radius: 20px;
            border: 1px solid var(--border);
            backdrop-filter: blur(4px);
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="header-brand">
            <div class="logo">LF</div>
            <div>
                <h1>Lafarge <span>Site Operations Platform</span></h1>
                <div class="subtitle">Truck Traffic Control Center</div>
            </div>
        </div>
        <div class="header-status">
            <div class="status-indicator">
                <span class="dot"></span>
                <span>All Systems Operational</span>
            </div>
            <span class="header-meta">v{APP_VERSION}</span>
        </div>
    </header>

    <div class="container">
        <!-- ============================================================
             SECTION 1 — Business Metrics
             ============================================================ -->
        <div class="section-title">
            <span class="icon">&#9881;</span> Business Metrics — Site Operations
        </div>
        <div class="metrics-grid">
            <div class="metric-card accent">
                <div class="label">Trucks on Site</div>
                <div class="value">{trucks_on_site_count}</div>
                <div class="sub">Currently active</div>
            </div>
            <div class="metric-card green">
                <div class="label">Total Processed</div>
                <div class="value">{trucks_count}</div>
                <div class="sub">All time</div>
            </div>
            <div class="metric-card blue">
                <div class="label">Entries Today</div>
                <div class="value">{entries_today}</div>
                <div class="sub">Inbound</div>
            </div>
            <div class="metric-card">
                <div class="label">Exits Today</div>
                <div class="value">{exits_today}</div>
                <div class="sub">Outbound</div>
            </div>
        </div>

        <!-- ============================================================
             SECTION 2 — Platform Health
             ============================================================ -->
        <div class="section-title">
            <span class="icon">&#9881;</span> Platform Health — Infrastructure Status
        </div>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="label">CPU Usage</div>
                <div class="value">{system["cpu_usage_percent"]}<span class="unit">%</span></div>
                <div class="progress-bar">
                    <div class="fill fill-{cpu_class}" style="width:{system["cpu_usage_percent"]}%"></div>
                </div>
            </div>
            <div class="metric-card">
                <div class="label">Memory Usage</div>
                <div class="value">{system["memory_usage_percent"]}<span class="unit">%</span></div>
                <div class="progress-bar">
                    <div class="fill fill-{mem_class}" style="width:{system["memory_usage_percent"]}%"></div>
                </div>
            </div>
            <div class="metric-card">
                <div class="label">Memory Usage</div>
                <div class="value">{system["memory_usage_percent"]}<span class="unit">%</span></div>
                <div class="progress-bar">
                    <div class="fill fill-{mem_class}" style="width:{system["memory_usage_percent"]}%"></div>
                </div>
            </div>
            <div class="metric-card">
                <div class="label">Active Instances</div>
                <div class="value">{system["active_instances"]}<span class="unit">nodes</span></div>
                <div class="sub">EC2 serving traffic</div>
            </div>
            <div class="metric-card">
                <div class="label">S3 Storage</div>
                <div class="value">{system["s3_storage_mb"]}<span class="unit">MB</span></div>
                <div class="sub">Traffic logs bucket</div>
            </div>
            <div class="metric-card">
                <div class="label">API Latency (P95)</div>
                <div class="value">{system["api_latency_p95_seconds"]}<span class="unit">s</span></div>
                <div class="sub">Response time</div>
            </div>
            <div class="metric-card">
                <div class="label">Overall Status</div>
                <div class="value" style="color: {overall_color}">
                    {system["overall_status"].upper()}
                </div>
                <div class="sub">Platform health</div>
            </div>
        </div>

        <!-- ============================================================
             SECTION 3 — Traffic Flow Chart
             ============================================================ -->
        <div class="section-title">
            <span class="icon">&#9881;</span> Truck Traffic Flow — Last 24 Hours
        </div>
        <div class="chart-wrapper">
            <canvas id="trafficChart"></canvas>
        </div>

        <!-- ============================================================
             SECTION 4 — Recent Movements
             ============================================================ -->
        <div class="section-title">
            <span class="icon">&#9881;</span> Recent Movements — Live Feed
        </div>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Truck ID</th>
                        <th>License Plate</th>
                        <th>Status</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    {trucks_rows}
                </tbody>
            </table>
        </div>
    </div>

    <footer class="footer">
        Lafarge Site Operations &mdash; Meknès Industrial Platform &mdash; Truck Traffic Management System v{APP_VERSION}
    </footer>

    <div class="last-updated" id="lastUpdated"></div>

    <script>
        // ---- Traffic flow chart ----
        const trafficData = {traffic_json};
        const hours = trafficData.map(d => String(d.hour).padStart(2, '0') + ':00');
        const entries = trafficData.map(d => d.entries);

        const ctx = document.getElementById('trafficChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: hours,
                datasets: [{{
                    label: 'Truck Entries',
                    data: entries,
                    borderColor: '#EE7203',
                    backgroundColor: 'rgba(238,114,3,0.08)',
                    borderWidth: 2,
                    pointRadius: 2,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#EE7203',
                    fill: true,
                    tension: 0.3,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        backgroundColor: '#1e293b',
                        titleColor: '#f1f5f9',
                        bodyColor: '#94a3b8',
                        borderColor: '#2d3a4e',
                        borderWidth: 1,
                        padding: 12,
                        cornerRadius: 8,
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{ color: 'rgba(45,58,78,0.3)', drawBorder: false }},
                        ticks: {{ color: '#64748b', font: {{ size: 11 }} }}
                    }},
                    y: {{
                        beginAtZero: true,
                        grid: {{ color: 'rgba(45,58,78,0.3)', drawBorder: false }},
                        ticks: {{ color: '#64748b', font: {{ size: 11 }} }}
                    }}
                }},
                interaction: {{
                    intersect: false,
                    mode: 'index',
                }}
            }}
        }});

        // ---- Last-updated timestamp ----
        document.getElementById('lastUpdated').textContent =
            'Last updated: ' + new Date().toLocaleTimeString('en-GB', {{ hour12: false }});
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content, status_code=200)


# --------------------------------------------------------------------------
# Route : Health check (utilisé par le Target Group du Load Balancer AWS)
# --------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# --------------------------------------------------------------------------
# Route : JSON metrics for dashboard real-time updates
# --------------------------------------------------------------------------
@app.get("/api/metrics")
async def api_metrics():
    s3 = _get_s3_service()
    monitoring = _get_monitoring_service()

    try:
        logs = s3.list_truck_logs()
    except Exception:
        logs = []

    if not logs and TRUCKS_REGISTRY:
        for truck_id, truck in TRUCKS_REGISTRY.items():
            event = "truck_entry" if truck["status"] == "on_site" else "truck_exit"
            logs.append(
                {
                    "truck_id": truck_id,
                    "license_plate": truck["plate"],
                    "event": event,
                    "event_time": truck["entry_time"],
                }
            )

    trucks_count = len(logs)
    trucks_on_site = sum(
        1 for t in logs if t.get("event") == "truck_entry" and not t.get("exit_time")
    )
    entries_today = sum(1 for t in logs if t.get("event") == "truck_entry")
    exits_today = sum(1 for t in logs if t.get("event") == "truck_exit")

    system = monitoring.get_system_status()
    traffic_history = monitoring.get_traffic_history()

    return {
        "business": {
            "total_trucks": trucks_count,
            "trucks_on_site": trucks_on_site,
            "entries_today": entries_today,
            "exits_today": exits_today,
        },
        "platform": system,
        "traffic_history": traffic_history,
    }


# --------------------------------------------------------------------------
# Route : Prometheus /metrics
# --------------------------------------------------------------------------
@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --------------------------------------------------------------------------
# Routes API métier
# --------------------------------------------------------------------------
@app.get("/api/trucks")
async def list_trucks():
    s3 = _get_s3_service()
    logs = s3.list_truck_logs()
    return JSONResponse(content=logs)


@app.post("/api/trucks/enter")
@limiter.limit("10/minute")
async def truck_enter(request: Request, plate: str, background_tasks: BackgroundTasks):
    truck_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    TRUCKS_REGISTRY[truck_id] = {
        "id": truck_id,
        "plate": plate,
        "status": "on_site",
        "entry_time": now_iso,
        "exit_time": None,
    }

    # Simulation du temps de pesée au pont-bascule (observabilité métier)
    weighing_time = random.uniform(15, 90)
    TRUCK_WEIGHING_DURATION_SECONDS.observe(weighing_time)

    TRUCKS_PROCESSED_TOTAL.labels(operation="entry").inc()
    TRUCKS_ON_SITE.inc()

    # --- Background upload to LocalStack S3 ---
    log_payload = {
        "event": "truck_entry",
        "truck_id": truck_id,
        "license_plate": plate,
        "event_time": now_iso,
        "gate_id": "GATE-A",
        "status": "APPROVED",
    }
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    object_key = f"traffic_logs/{date_prefix}/{truck_id}_{int(time.time())}.json"

    s3 = _get_s3_service()
    background_tasks.add_task(
        s3.upload_json,
        object_key,
        json.dumps(log_payload, indent=2),
    )
    logger.info("Scheduled S3 upload for truck entry: %s", object_key)

    return {"message": "Camion enregistré", "truck_id": truck_id}


@app.post(
    "/api/trucks/exit",
    responses={
        404: {"description": "Camion introuvable"},
        409: {"description": "Camion déjà sorti"},
    },
)
@limiter.limit("10/minute")
async def truck_exit(
    request: Request, truck_id: str, background_tasks: BackgroundTasks
):
    s3 = _get_s3_service()
    logs = s3.list_truck_logs()

    # Look for the truck's entry log in S3 (event == "truck_entry")
    truck_logs = [t for t in logs if t.get("truck_id") == truck_id]
    entry_log = next((t for t in truck_logs if t.get("event") == "truck_entry"), None)
    exit_log = next((t for t in truck_logs if t.get("event") == "truck_exit"), None)

    # Check in-memory registry first for immediate duplicate detection
    truck = TRUCKS_REGISTRY.get(truck_id)
    if truck:
        if truck.get("status") == "exited":
            raise HTTPException(status_code=409, detail="Camion déjà sorti")
    elif exit_log:
        raise HTTPException(status_code=409, detail="Camion déjà sorti")

    if entry_log:
        plate = entry_log["license_plate"]
        entry_time = entry_log["event_time"]
    else:
        # Fallback: check in-memory registry (only works for current session)
        truck = TRUCKS_REGISTRY.get(truck_id)
        if not truck:
            raise HTTPException(status_code=404, detail="Camion introuvable")
        plate = truck["plate"]
        entry_time = truck["entry_time"]

    now_iso = datetime.now(timezone.utc).isoformat()

    TRUCKS_PROCESSED_TOTAL.labels(operation="exit").inc()
    TRUCKS_ON_SITE.dec()

    # Update in-memory registry status
    if truck_id in TRUCKS_REGISTRY:
        TRUCKS_REGISTRY[truck_id]["status"] = "exited"
        TRUCKS_REGISTRY[truck_id]["exit_time"] = now_iso

    # --- Background upload to LocalStack S3 ---
    log_payload = {
        "event": "truck_exit",
        "truck_id": truck_id,
        "license_plate": plate,
        "entry_time": entry_time,
        "exit_time": now_iso,
        "gate_id": "GATE-A",
        "status": "COMPLETED",
    }
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    object_key = f"traffic_logs/{date_prefix}/{truck_id}_{int(time.time())}.json"

    s3 = _get_s3_service()
    background_tasks.add_task(
        s3.upload_json,
        object_key,
        json.dumps(log_payload, indent=2),
    )
    logger.info("Scheduled S3 upload for truck exit: %s", object_key)

    return {"message": "Sortie du camion enregistrée", "truck_id": truck_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app", host=os.getenv("APP_HOST", "0.0.0.0"), port=8000, reload=False
    )
