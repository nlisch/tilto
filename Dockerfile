FROM python:3.10-slim

WORKDIR /app

# Installation des dépendances système (ajout de bc)
RUN apt-get update && apt-get install -y \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    bc \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie de l'application
COPY . .

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    FLASK_APP=wsgi.py \
    PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1

# Compilation des traductions
RUN pybabel compile -d translations || echo "No translations to compile"

# Configuration du script d'entrée
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Healthcheck optimisé
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT}/health || exit 1

EXPOSE ${PORT}
ENTRYPOINT ["docker-entrypoint.sh"]

# Utiliser le fichier wsgi.py
CMD exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --threads 4 \
    --worker-class gthread \
    --timeout 300 \
    --graceful-timeout 60 \
    --keep-alive 5 \
    --max-requests 800 \
    --max-requests-jitter 100 \
    --preload \
    --log-level info \
    --access-logfile "-" \
    --error-logfile "-" \
    --capture-output \
    wsgi:application