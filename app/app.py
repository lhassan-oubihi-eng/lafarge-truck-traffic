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

import os
import random
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

APP_NAME = "lafarge-truck-traffic"
APP_VERSION = "1.0.0"

app = FastAPI(title="Lafarge Truck Traffic Management", version=APP_VERSION)

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
    trucks_count = len(TRUCKS_REGISTRY)
    trucks_on_site_count = sum(
        1 for t in TRUCKS_REGISTRY.values() if t["status"] == "on_site"
    )
    trucks_rows = ""
    for truck_id, data in list(TRUCKS_REGISTRY.items())[-10:][::-1]:
        trucks_rows += f"""
        <tr>
            <td>{truck_id[:8]}</td>
            <td>{data['plate']}</td>
            <td>{data['status']}</td>
            <td>{data['entry_time']}</td>
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
    return JSONResponse(content=list(TRUCKS_REGISTRY.values()))


@app.post("/api/trucks/enter")
async def truck_enter(plate: str):
    truck_id = str(uuid.uuid4())
    TRUCKS_REGISTRY[truck_id] = {
        "id": truck_id,
        "plate": plate,
        "status": "on_site",
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "exit_time": None,
    }

    # Simulation du temps de pesée au pont-bascule (observabilité métier)
    weighing_time = random.uniform(15, 90)
    TRUCK_WEIGHING_DURATION_SECONDS.observe(weighing_time)

    TRUCKS_PROCESSED_TOTAL.labels(operation="entry").inc()
    TRUCKS_ON_SITE.inc()

    return {"message": "Camion enregistré", "truck_id": truck_id}


@app.post(
    "/api/trucks/exit",
    responses={
        404: {"description": "Camion introuvable"},
        409: {"description": "Camion déjà sorti"},
    },
)
async def truck_exit(truck_id: str):
    truck = TRUCKS_REGISTRY.get(truck_id)
    if not truck:
        raise HTTPException(status_code=404, detail="Camion introuvable")
    if truck["status"] == "exited":
        raise HTTPException(status_code=409, detail="Camion déjà sorti")

    truck["status"] = "exited"
    truck["exit_time"] = datetime.now(timezone.utc).isoformat()

    TRUCKS_PROCESSED_TOTAL.labels(operation="exit").inc()
    TRUCKS_ON_SITE.dec()

    return {"message": "Sortie du camion enregistrée", "truck_id": truck_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=os.getenv("APP_HOST", "0.0.0.0"), port=8000, reload=False)
