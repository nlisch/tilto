from flask import Blueprint, jsonify, request, render_template, flash, redirect, url_for, current_app, g
from flask_login import login_required, current_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from forms import ChangePasswordForm
import logging
from flask_babel import _, gettext

user_bp = Blueprint('user', __name__)
logger = logging.getLogger(__name__)


def log_consent_change(mysql, user_id, consent_type, consent_status, source='account_page'):
    """Logger un changement de consentement dans l'historique"""
    try:
        cursor = mysql.connection.cursor()
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip_address and ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()
        
        cursor.execute("""
            INSERT INTO user_consent_history 
                (user_id, consent_type, consent_status, ip_address, source)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, consent_type, consent_status, ip_address, source))
        
        mysql.connection.commit()
        cursor.close()
        
        action = "OPT-IN" if consent_status else "OPT-OUT"
        logger.info(f"Consent logged: user_id={user_id}, type={consent_type}, status={action}, source={source}")
        return True
    except Exception as e:
        logger.error(f"Error logging consent: {e}")
        return False


@user_bp.route('/mon-compte', methods=['GET', 'POST'])
@login_required
def my_account():
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()

    try:
        if request.method == 'POST':
            newsletter_subscription = request.form.get('newsletter_subscription') == 'on'
            partner_consent = request.form.get('partner_consent') == 'on'
            
            cursor.execute("""
                SELECT newsletter_subscription, partner_consent
                FROM users WHERE user_id = %s
            """, (current_user.id,))
            current_vals = cursor.fetchone()
            
            if current_vals:
                current_newsletter = current_vals[0] if current_vals[0] is not None else False
                current_partner = current_vals[1] if current_vals[1] is not None else False
                
                if current_newsletter != newsletter_subscription:
                    log_consent_change(mysql, current_user.id, 'newsletter', newsletter_subscription)
                
                if current_partner != partner_consent:
                    log_consent_change(mysql, current_user.id, 'partner', partner_consent)
            
            cursor.execute("""
                UPDATE users 
                SET newsletter_subscription = %s, partner_consent = %s, updated_at = NOW()
                WHERE user_id = %s
            """, (newsletter_subscription, partner_consent, current_user.id))
            mysql.connection.commit()
            flash(_('Vos préférences de communication ont été mises à jour'), 'success')

        cursor.execute("""
            SELECT COUNT(DISTINCT qu.quiz_id) as quizzes_completed,
                   SUM(qu.questions_answered_count) as total_questions_answered,
                   u.newsletter_subscription,
                   u.partner_consent
            FROM users u
            LEFT JOIN quiz_user qu ON u.user_id = qu.user_id AND qu.quiz_status = 'completed'
            WHERE u.user_id = %s
            GROUP BY u.user_id
        """, (current_user.id,))
        stats_row = cursor.fetchone()
        
        stats = {
            'quizzes_completed': stats_row[0] if stats_row else 0,
            'total_questions_answered': stats_row[1] if stats_row else 0,
            'newsletter_subscription': stats_row[2] if stats_row else False,
            'partner_consent': stats_row[3] if stats_row else False
        }
        
        user_quizzes = []
        quiz_types = []
        quiz_labels = []
        questions_answered = []

        if stats['quizzes_completed'] > 0:
            cursor.execute("""
                SELECT qu.quiz_id, qc.quiz_type, qu.questions_answered_count, qu.created_at, qu.updated_at
                FROM quiz_user qu
                JOIN quiz_catalog qc ON qu.quiz_id = qc.quiz_id
                WHERE qu.user_id = %s AND qu.quiz_status = 'completed'
                ORDER BY qu.updated_at DESC
            """, (current_user.id,))
            user_quizzes = [
                {
                    'quiz_id': row[0],
                    'quiz_type': row[1],
                    'questions_answered': row[2],
                    'started_at': row[3].strftime('%Y-%m-%d %H:%M'),
                    'completed_at': row[4].strftime('%Y-%m-%d %H:%M')
                }
                for row in cursor.fetchall()
            ]
            
            quiz_types = list(set(quiz['quiz_type'] for quiz in user_quizzes))
            quiz_labels = [_("Quiz %(id)s", id=quiz['quiz_id']) for quiz in user_quizzes]
            questions_answered = [quiz['questions_answered'] for quiz in user_quizzes]
        
        return render_template('user/my_account.html', 
                               stats=stats, 
                               user_quizzes=user_quizzes,
                               quiz_types=quiz_types,
                               quiz_labels=quiz_labels,
                               questions_answered=questions_answered,
                               has_completed_quizzes=stats['quizzes_completed'] > 0)
    
    except Exception as e:
        logger.error(_("Error retrieving account data: %(error)s", error=e), exc_info=True)
        flash(_("An error occurred while loading your data."), 'error')
        return redirect(url_for('auth.dashboard', lang_code=g.lang_code))
    
    finally:
        cursor.close()


@user_bp.route('/changer-mot-de-passe', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    Gère le changement OU la création de mot de passe
    """
    mysql = current_app.mysql
    
    # ✅ Vérifier si l'utilisateur a déjà un mot de passe
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT password FROM users WHERE user_id = %s", (current_user.id,))
    user = cursor.fetchone()
    cursor.close()
    
    has_password = user and user[0] is not None
    
    if request.method == 'GET':
        form = ChangePasswordForm()
        return render_template('auth/change_password.html', 
                               form=form, 
                               has_password=has_password)
    
    try:
        if request.is_json:
            data = request.get_json()
            old_password = data.get('ancien_mot_de_passe', '').strip()
            new_password = data.get('nouveau_mot_de_passe', '').strip()
            confirm_password = data.get('confirmer_mot_de_passe', '').strip()
        else:
            form = ChangePasswordForm()
            if not form.validate_on_submit():
                return render_template('auth/change_password.html', 
                                       form=form, 
                                       has_password=has_password)
            old_password = form.ancien_mot_de_passe.data
            new_password = form.nouveau_mot_de_passe.data
            confirm_password = form.confirmer_mot_de_passe.data
        
        # ✅ CAS 1 : Création du premier mot de passe (pas d'ancien requis)
        if not has_password:
            if not new_password or not confirm_password:
                if request.is_json:
                    return jsonify({"success": False, "message": "Tous les champs sont requis."}), 400
                flash("Tous les champs sont requis.", 'error')
                return redirect(url_for('user.change_password'))
            
            if new_password != confirm_password:
                if request.is_json:
                    return jsonify({"success": False, "message": "Les mots de passe ne correspondent pas."}), 400
                flash("Les mots de passe ne correspondent pas.", 'error')
                return redirect(url_for('user.change_password'))
            
            if len(new_password) < 8:
                if request.is_json:
                    return jsonify({"success": False, "message": "Le mot de passe doit contenir au moins 8 caractères."}), 400
                flash("Le mot de passe doit contenir au moins 8 caractères.", 'error')
                return redirect(url_for('user.change_password'))
            
            # ✅ Créer le mot de passe
            hashed_password = generate_password_hash(new_password)
            cursor = mysql.connection.cursor()
            cursor.execute("""
                UPDATE users 
                SET password = %s, updated_at = NOW() 
                WHERE user_id = %s
            """, (hashed_password, current_user.id))
            mysql.connection.commit()
            cursor.close()
            
            logger.info(f"✅ Premier mot de passe créé pour user_id: {current_user.id}")
            
            if request.is_json:
                return jsonify({"success": True, "message": "🔒 Mot de passe créé avec succès ! Tu peux maintenant te connecter avec."}), 200
            
            flash("🔒 Mot de passe créé avec succès ! Tu peux maintenant te connecter avec.", 'success')
            return redirect(url_for('user.my_account'))
        
        # ✅ CAS 2 : Changement de mot de passe (ancien requis)
        else:
            if not old_password or not new_password or not confirm_password:
                if request.is_json:
                    return jsonify({"success": False, "message": "Tous les champs sont requis."}), 400
                flash("Tous les champs sont requis.", 'error')
                return redirect(url_for('user.change_password'))
            
            if new_password != confirm_password:
                if request.is_json:
                    return jsonify({"success": False, "message": "Les nouveaux mots de passe ne correspondent pas."}), 400
                flash("Les nouveaux mots de passe ne correspondent pas.", 'error')
                return redirect(url_for('user.change_password'))
            
            if len(new_password) < 8:
                if request.is_json:
                    return jsonify({"success": False, "message": "Le mot de passe doit contenir au moins 8 caractères."}), 400
                flash("Le mot de passe doit contenir au moins 8 caractères.", 'error')
                return redirect(url_for('user.change_password'))
            
            cursor = mysql.connection.cursor()
            cursor.execute("SELECT password FROM users WHERE user_id = %s", (current_user.id,))
            user = cursor.fetchone()
            
            if not user:
                cursor.close()
                if request.is_json:
                    return jsonify({"success": False, "message": "Utilisateur introuvable."}), 404
                flash("Utilisateur introuvable.", 'error')
                return redirect(url_for('user.my_account'))
            
            if not check_password_hash(user[0], old_password):
                cursor.close()
                if request.is_json:
                    return jsonify({"success": False, "message": "L'ancien mot de passe est incorrect."}), 400
                flash("L'ancien mot de passe est incorrect.", 'error')
                return redirect(url_for('user.change_password'))
            
            hashed_password = generate_password_hash(new_password)
            cursor.execute("""
                UPDATE users 
                SET password = %s, updated_at = NOW() 
                WHERE user_id = %s
            """, (hashed_password, current_user.id))
            mysql.connection.commit()
            cursor.close()
            
            logger.info(f"✅ Mot de passe changé pour user_id: {current_user.id}")
            
            if request.is_json:
                return jsonify({"success": True, "message": "Ton mot de passe a été changé avec succès ! 🎉"}), 200
            
            flash("Ton mot de passe a été changé avec succès ! 🎉", 'success')
            return redirect(url_for('user.my_account'))
        
    except Exception as e:
        logger.error(f"Error changing password: {str(e)}", exc_info=True)
        if request.is_json:
            return jsonify({"success": False, "message": "Une erreur est survenue. Réessaye plus tard."}), 500
        flash("Une erreur est survenue. Réessaye plus tard.", 'error')
        return redirect(url_for('user.change_password'))


@user_bp.route('/supprimer-compte', methods=['POST'])
@login_required
def supprimer_compte():
    user_id = current_user.id
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    
    try:
        # answer_user has no user_id — delete via quiz_session_id from quiz_user
        cursor.execute("""
            DELETE au FROM answer_user au
            INNER JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
            WHERE qu.user_id = %s
        """, (user_id,))
        
        cursor.execute("DELETE FROM quiz_user WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_consent_history WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        
        mysql.connection.commit()
        logout_user()
        flash(_('Your account has been successfully deleted.'), 'success')
        return jsonify({"success": True, "message": _("Account successfully deleted")}), 200
    except Exception as e:
        mysql.connection.rollback()
        logger.error(_("Error deleting account: %(error)s", error=e), exc_info=True)
        return jsonify({"success": False, "message": _("An error occurred while deleting the account")}), 500
    finally:
        cursor.close()

@user_bp.route('/set-password/<token>', methods=['GET', 'POST'])
def set_password(token):
    """Définir un mot de passe pour un compte créé sans (post-achat landing)."""
    from models import User

    user_id = User.verify_reset_token(token, expires_sec=86400 * 7)
    if not user_id:
        flash(_('Ce lien a expiré.'), 'error')
        return redirect(url_for('auth.login'))

    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("SELECT user_id, email, username, password FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()

        if not user_data:
            flash(_('Utilisateur introuvable.'), 'error')
            return redirect('/')

        # Déjà un mot de passe → login
        if user_data[3] is not None:
            flash(_('Votre mot de passe est déjà défini. Connectez-vous.'), 'info')
            return redirect(url_for('auth.login'))

        if request.method == 'GET':
            return render_template('auth/set_password.html', email=user_data[1], token=token)

        password = request.form.get('password', '').strip()
        password_confirm = request.form.get('password_confirm', '').strip()

        if not password or len(password) < 8:
            flash(_('Le mot de passe doit contenir au moins 8 caractères.'), 'error')
            return render_template('auth/set_password.html', email=user_data[1], token=token)

        if password != password_confirm:
            flash(_('Les mots de passe ne correspondent pas.'), 'error')
            return render_template('auth/set_password.html', email=user_data[1], token=token)

        hashed = generate_password_hash(password)
        cursor.execute("""
            UPDATE users SET password = %s, user_status = 'user', 
                             onboarding_stage = 'completed', updated_at = NOW()
            WHERE user_id = %s
        """, (hashed, user_id))
        mysql.connection.commit()

        # Connecter automatiquement
        from flask_login import login_user
        user = User(user_id=user_data[0], username=user_data[2], email=user_data[1], user_status='user')
        login_user(user)

        flash(_('Mot de passe créé avec succès ! Bienvenue 🎉'), 'success')
        return redirect(url_for('auth.dashboard'))

    except Exception as e:
        logger.error(f"Erreur set_password: {e}", exc_info=True)
        flash(_('Une erreur est survenue.'), 'error')
        return redirect('/')
    finally:
        cursor.close()