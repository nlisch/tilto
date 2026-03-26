# decorators/auth_decorators.py
from functools import wraps
from flask import session, redirect, url_for, flash, current_app, request, jsonify
from flask_login import current_user
from flask_babel import Babel, gettext as _, lazy_gettext as _l, gettext
import logging

logger = logging.getLogger(__name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash(_('Vous devez vous connecter pour accéder à cette page.'), 'error')
            return redirect(url_for('auth.login'))
        if current_user.user_status != 'admin':
            flash(_('Accès refusé.'), 'error')
            return redirect(url_for('auth.dashboard'))
        if not session.get('two_factor_authenticated'):
            flash(_('Veuillez compléter l\'authentification à deux facteurs.'), 'warning')
            return redirect(url_for('auth.two_factor'))
        return f(*args, **kwargs)
    return decorated_function


def check_token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Extraire quiz_id des kwargs ou des paramètres d'URL
        quiz_id = kwargs.get('quiz_id') or request.args.get('quiz_id')
        
        if not quiz_id and request.is_json:
            data = request.get_json()
            logger.debug(f"Received JSON data: {data}")  # Ajout de log
            quiz_id = data.get('quiz_id') or data.get('quizId')  # Accepter les deux formats
    
        if not quiz_id:
            if request.is_json:
                logger.warning("Quiz ID is missing in JSON data.")
                return jsonify({'error': _('Quiz ID is required')}), 400
            flash(_('Quiz ID is required'), 'error')
            return redirect(url_for('auth.dashboard'))
    
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
    
        try:
            # 1. Vérifier si ce quiz existe
            cursor.execute("""
                SELECT quiz_id FROM quiz_catalog 
                WHERE quiz_id = %s
            """, (quiz_id,))
            
            if not cursor.fetchone():
                logger.warning(f"Tentative d'accès à un quiz inexistant: {quiz_id} par l'utilisateur {current_user.id}")
                if request.is_json:
                    return jsonify({'error': _('Invalid quiz ID')}), 404
                flash(_('Ce quiz n\'existe pas'), 'error')
                return redirect(url_for('auth.dashboard'))
    
            # 2. Vérifier si l'utilisateur a un token valide ou non pour ce quiz
            cursor.execute("""
                SELECT token_code FROM tokens 
                WHERE user_id = %s AND quiz_id = %s
            """, (current_user.id, quiz_id))
            
            if not cursor.fetchone():
                logger.warning(f"Tentative d'accès sans token valide: quiz {quiz_id} par l'utilisateur {current_user.id}")
                if request.is_json:
                    return jsonify({'error': _('Token required to access this quiz')}), 403
                flash(_('Vous devez avoir un jeton valide pour accéder à ce quiz'), 'warning')
                return redirect(url_for('tokens.shop'))
            
            return f(*args, **kwargs)
            
        except Exception as e:
            logger.error(f"Erreur lors de la vérification du token: {str(e)}")
            if request.is_json:
                return jsonify({'error': _('An error occurred')}), 500
            flash(_('Une erreur est survenue'), 'error')
            return redirect(url_for('auth.dashboard'))
            
        finally:
            cursor.close()
            
    return decorated_function

def ajax_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(error="Session expired", redirect=url_for('auth.login')), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# Assurez-vous que le décorateur est exporté
__all__ = ['admin_required', 'check_token_required', 'ajax_login_required']