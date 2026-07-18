# --------------------------------------------------------------------------
# Image de production pour l'application Lafarge Truck Traffic Management
# --------------------------------------------------------------------------
FROM python:3.12-slim

# Empêche Python de générer des fichiers .pyc et force le flush des logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Installation des dépendances (couche mise en cache séparément du code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code applicatif
COPY app.py .
COPY services/ ./services/

# Utilisateur non-root pour la sécurité
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Health check natif Docker (utile en local / debug)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
