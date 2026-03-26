from flask import Blueprint, request, jsonify, render_template, session, current_app
import json
import logging
from extensions import csrf

logger = logging.getLogger(__name__)

cookie_bp = Blueprint('cookie', __name__, url_prefix='/cookie')

@cookie_bp.route('/consent', methods=['POST'])
@csrf.exempt
def set_cookie_consent():
    try:
        # Vérifier si le contenu est bien du JSON
        if not request.is_json:
            logger.warning("Requête non-JSON reçue pour /cookie/consent")
            return jsonify({"error": "Le contenu doit être au format JSON"}), 400
            
        data = request.get_json()
        if not data or not isinstance(data, dict):
            logger.warning(f"Format de données invalide: {data}")
            return jsonify({"error": "Format de données invalide"}), 400
            
        # Valider les types de consentement
        consent_types = ['necessary', 'analytics', 'marketing', 'preferences']
        consent_data = {}
        
        # 'necessary' est toujours True (cookies essentiels)
        consent_data['necessary'] = True
        
        for consent_type in consent_types:
            if consent_type != 'necessary':  # Skip 'necessary' car déjà défini
                consent_data[consent_type] = bool(data.get(consent_type, False))
        
        # Stocker le consentement dans la session
        session['cookie_consent'] = consent_data
        session.modified = True
        
        logger.info(f"Consentement cookies mis à jour: {consent_data}")
        
        return jsonify({"status": "success", "message": "Préférences de cookies enregistrées"}), 200
    except Exception as e:
        logger.error(f"Erreur lors du traitement du consentement aux cookies: {e}", exc_info=True)
        return jsonify({"error": f"Une erreur est survenue: {str(e)}"}), 500

@cookie_bp.route('/status', methods=['GET'])
def get_cookie_consent():
    try:
        # Récupérer les données de consentement de la session
        consent = session.get('cookie_consent', None)
        logger.debug(f"Requête status - Consentement actuel: {consent}")
        
        # Définir explicitement le type de contenu comme JSON
        response = jsonify({"status": "success", "consent": consent})
        response.headers['Content-Type'] = 'application/json'
        return response, 200
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut des cookies: {e}", exc_info=True)
        # Même en cas d'erreur, renvoyer du JSON
        error_response = jsonify({"status": "error", "message": str(e)})
        error_response.headers['Content-Type'] = 'application/json'
        return error_response, 500