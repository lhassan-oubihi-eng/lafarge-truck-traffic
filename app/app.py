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
# Route : Dashboard HTML
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    s3 = _get_s3_service()
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

    trucks_count = len(logs)
    trucks_on_site_count = sum(
        1 for t in logs if t.get("event") == "truck_entry" and not t.get("exit_time")
    )
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
            <td>{truck_id[:8]}</td>
            <td>{plate}</td>
            <td class="{status_class}">{status_label}</td>
            <td>{event_time}</td>
        </tr>"""

    if not trucks_rows:
        trucks_rows = "<tr><td colspan='4' class='empty'>Aucun camion enregistré pour le moment</td></tr>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Lafarge | Truck Traffic Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {{
                --lafarge-blue: #003057;
                --lafarge-orange: #EE7203;
                --bg: #f4f6f8;
            }}
            * {{ box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Arial, sans-serif;
                background: var(--bg);
                margin: 0;
                color: #1a1a1a;
            }}
            header {{
                background: var(--lafarge-blue);
                color: white;
                padding: 24px 40px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }}
            header h1 {{
                margin: 0;
                font-size: 22px;
                font-weight: 600;
            }}
            header span {{
                color: var(--lafarge-orange);
                font-weight: 700;
            }}
            .container {{
                padding: 32px 40px;
            }}
            .cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 20px;
                margin-bottom: 32px;
            }}
            .card {{
                background: white;
                border-radius: 10px;
                padding: 20px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.08);
                border-left: 5px solid var(--lafarge-orange);
            }}
            .card h2 {{
                margin: 0;
                font-size: 32px;
                color: var(--lafarge-blue);
            }}
            .card p {{
                margin: 6px 0 0;
                color: #666;
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            }}
            th, td {{
                padding: 12px 16px;
                text-align: left;
                border-bottom: 1px solid #eee;
                font-size: 14px;
            }}
            th {{
                background: var(--lafarge-blue);
                color: white;
                text-transform: uppercase;
                font-size: 12px;
            }}
            .empty {{ text-align: center; color: #999; padding: 24px; }}
            footer {{
                text-align: center;
                padding: 20px;
                color: #999;
                font-size: 12px;
            }}
            .status-onsite {{ color: #1b8a3d; font-weight: 600; }}
            .status-exited {{ color: #999; }}
        </style>
    </head>
    <body>
        <header>
            <h1>Lafarge<span> | Truck Traffic Management</span></h1>
            <div>Statut système : <strong style="color:#4caf50;">● Opérationnel</strong></div>
        </header>
        <div class="container">
            <div class="cards">
                <div class="card">
                    <h2>{trucks_count}</h2>
                    <p>Camions suivis (session)</p>
                </div>
                <div class="card">
                    <h2>{trucks_on_site_count}</h2>
                    <p>Camions actuellement sur site</p>
                </div>
                <div class="card">
                    <h2>{APP_VERSION}</h2>
                    <p>Version de l'application</p>
                </div>
            </div>
            <h3>Derniers mouvements enregistrés</h3>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Plaque</th>
                        <th>Statut</th>
                        <th>Heure d'entrée</th>
                    </tr>
                </thead>
                <tbody>
                    {trucks_rows}
                </tbody>
            </table>
        </div>
        <footer>
            Lafarge Site Meknès &mdash; Truck Traffic Management System v{APP_VERSION}
        </footer>
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
async def truck_enter(plate: str, background_tasks: BackgroundTasks):
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
async def truck_exit(truck_id: str, background_tasks: BackgroundTasks):
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
