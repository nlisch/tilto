
#!/usr/bin/env python3
"""
Point d'entrée WSGI pour l'application Flask
Utilisé par Gunicorn en production
"""

from app import create_app

# Créer l'instance de l'application
application = create_app()

if __name__ == "__main__":
    application.run()