#!/bin/bash
set -e

# Timestamp de démarrage
STARTUP_START=$(date +%s.%N)

# Fonction pour calculer le temps écoulé (compatible sans bc si nécessaire)
elapsed_time() {
    local current=$(date +%s.%N)
    if command -v bc >/dev/null 2>&1; then
        local elapsed=$(echo "$current - $STARTUP_START" | bc -l)
        printf "%.3f" $elapsed
    else
        # Fallback sans bc
        python3 -c "print(f'{$current - $STARTUP_START:.3f}')"
    fi
}

echo "=== Démarrage de l'application Tilto ==="
echo "🕐 Début du démarrage: $(date -Iseconds)"
echo "Port: ${PORT:-8080}"
echo "Python: $(python --version)"

# Vérification de l'environnement
echo "⚙️ [$(elapsed_time)s] Vérification de l'environnement..."

if [ -n "$GOOGLE_CLOUD_PROJECT" ]; then
    echo "🏭 Environnement de production détecté: $GOOGLE_CLOUD_PROJECT"
    export FLASK_DEBUG=False
    
    # Test de connectivité rapide
    echo "🔗 [$(elapsed_time)s] Test de connectivité..."
    
    # Vérifier l'accès aux secrets (timeout rapide)
    timeout 5s gcloud secrets versions access latest --secret="app-config" --format="get(payload.data)" > /dev/null 2>&1 || {
        echo "⚠️ Warning: Impossible d'accéder aux secrets rapidement"
    }
else
    echo "🔧 Environnement de développement détecté"
    export FLASK_DEBUG=True
fi

echo "✅ [$(elapsed_time)s] Configuration: FLASK_DEBUG=$FLASK_DEBUG"

# Pré-chauffage Python (import des modules critiques)
echo "🔥 [$(elapsed_time)s] Pré-chauffage Python..."
python -c "
try:
    import flask
    print('✓ Flask importé')
    from flask_mysqldb import MySQL
    print('✓ Flask-MySQLdb importé')
    import stripe
    print('✓ Stripe importé')
    print('✅ Modules critiques importés avec succès')
except ImportError as e:
    print(f'⚠️ Warning: Erreur d\'import - {e}')
except Exception as e:
    print(f'⚠️ Warning: Erreur générale - {e}')
" || echo "⚠️ Warning: Certains modules ont échoué"

echo "✅ [$(elapsed_time)s] Modules Python prêts"

# Information de performance
echo "🚀 [$(elapsed_time)s] Lancement de gunicorn..."
echo "Configuration: Workers=2, Threads=4, Concurrence=20"

# Log du temps total de préparation
PREP_TIME=$(elapsed_time)
echo "⏱️ Temps de préparation: ${PREP_TIME}s"

# Variables d'environnement pour tracer les temps dans l'app
export CONTAINER_STARTUP_TIME=$STARTUP_START
export CONTAINER_PREP_TIME=$PREP_TIME

# Lancement avec logging amélioré
echo "▶️ [$(elapsed_time)s] Exec gunicorn..."

# Exécution de la commande avec logging de démarrage
exec "$@"