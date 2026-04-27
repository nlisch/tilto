from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
import secrets
import string
import logging
from datetime import datetime, timedelta
import uuid
from flask_babel import _, gettext
from flask_mail import Message
from extensions import mail
from decorators import admin_required
from MySQLdb.cursors import DictCursor


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
logger = logging.getLogger(__name__)

def generate_secure_password(length=12):
    """Génère un mot de passe sécurisé"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password

@admin_bp.route('/dashboard_users')
@login_required
@admin_required
def dashboard():
    """Page principale d'administration avec liste complète des utilisateurs"""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        logger.info("Début récupération statistiques")
        
        # ✅ CORRECTION : Ajouter free_user et corriger les comptages
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE user_status = 'user'")
        total_customers = cursor.fetchone()['total']
        logger.info(f"Total clients (payants): {total_customers}")
        
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE user_status = 'free_user'")
        total_free_users = cursor.fetchone()['total']
        logger.info(f"Total utilisateurs gratuits: {total_free_users}")
        
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE user_status = 'lead'")
        total_leads = cursor.fetchone()['total']
        logger.info(f"Total leads: {total_leads}")
        
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE user_status = 'admin'")
        total_admins = cursor.fetchone()['total']
        logger.info(f"Total admins: {total_admins}")
        
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE user_status = 'coach'")
        total_coaches = cursor.fetchone()['total']
        logger.info(f"Total coaches: {total_coaches}")
        
        # Filtres et recherche
        logger.info("Récupération filtres")
        user_status_filter = request.args.get('user_status', '')
        search = request.args.get('search', '')
        
        # Pagination
        logger.info("Configuration pagination")
        page = int(request.args.get('page', 1))
        per_page = 20
        offset = (page - 1) * per_page
        
        # Construction de la requête avec filtres
        logger.info("Construction requête filtres")
        where_conditions = []
        params = []
        
        if user_status_filter:
            where_conditions.append("user_status = %s")
            params.append(user_status_filter)
            
        if search:
            where_conditions.append("(username LIKE %s OR email LIKE %s OR firstname LIKE %s OR lastname LIKE %s OR phone_number LIKE %s)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param, search_param, search_param])
        
        where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        # Compter le total
        logger.info("Comptage total users")
        count_query = f"SELECT COUNT(*) as total FROM users{where_clause}"
        cursor.execute(count_query, params)
        total_users = cursor.fetchone()['total']
        total_pages = (total_users + per_page - 1) // per_page
        logger.info(f"Total users: {total_users}, pages: {total_pages}")
        
        # Récupérer tous les utilisateurs avec filtres
        logger.info("Récupération liste users")
        query = f"""
            SELECT user_id, username, email, firstname, lastname, phone_number, user_status, 
                newsletter_subscription, partner_consent, privacy_policy_accepted, created_at
            FROM users
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])
        cursor.execute(query, params)
        all_users = cursor.fetchall()
        logger.info(f"Récupéré {len(all_users)} users")
        
        stats = {
            'total_customers': total_customers,
            'total_free_users': total_free_users,  # ✅ NOUVEAU
            'total_leads': total_leads,
            'total_admins': total_admins,
            'total_coaches': total_coaches,
            'all_users': all_users,
            'total_users': total_users,
            'total_pages': total_pages,
            'current_page': page
        }
        
        logger.info("Rendu template dashboard")
        return render_template('admin/dashboard.html', 
                             stats=stats,
                             user_status_filter=user_status_filter,
                             search=search)
        
    except Exception as e:
        logger.error(f"Erreur lors du chargement du dashboard admin: {e}", exc_info=True)
        flash(_('Erreur lors du chargement des données'), 'error')
        return redirect(url_for('auth.home'))
    finally:
        cursor.close()


@admin_bp.route('/user/<int:user_id>/reset-password', methods=['POST'])
@login_required
@admin_required
def reset_user_password(user_id):
    """Réinitialiser le mot de passe d'un utilisateur"""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Vérifier que l'utilisateur existe
        cursor.execute("SELECT username, email FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'message': 'Utilisateur introuvable'}), 404
        
        username, email = user
        
        # Générer un nouveau mot de passe
        new_password = generate_secure_password()
        hashed_password = generate_password_hash(new_password)
        
        # Mettre à jour en base
        cursor.execute("""
            UPDATE users 
            SET password = %s, updated_at = %s 
            WHERE user_id = %s
        """, (hashed_password, datetime.now(), user_id))
        mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'message': 'Mot de passe réinitialisé avec succès',
            'username': username,
            'new_password': new_password
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la réinitialisation du mot de passe: {e}")
        mysql.connection.rollback()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}), 500
    finally:
        cursor.close()

@admin_bp.route('/user/<int:user_id>/toggle-status', methods=['POST'])
@login_required
@admin_required
def toggle_user_status(user_id):
    """Changer le statut d'un utilisateur"""
    try:
        data = request.get_json()
        new_status = data.get('new_status')
        
        # Valider le nouveau statut
        valid_statuses = ['lead', 'customer', 'admin', 'coach']
        if new_status not in valid_statuses:
            return jsonify({'success': False, 'message': 'Statut invalide'}), 400
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Vérifier que l'utilisateur existe
        cursor.execute("SELECT user_status FROM users WHERE user_id = %s", (user_id,))
        current_status = cursor.fetchone()
        
        if not current_status:
            return jsonify({'success': False, 'message': 'Utilisateur introuvable'}), 404
        
        # Mettre à jour le statut
        cursor.execute("""
            UPDATE users 
            SET user_status = %s, updated_at = %s 
            WHERE user_id = %s
        """, (new_status, datetime.now(), user_id))
        mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'message': f'Statut changé vers {new_status}',
            'new_status': new_status
        })
        
    except Exception as e:
        logger.error(f"Erreur lors du changement de statut: {e}")
        mysql.connection.rollback()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}), 500
    finally:
        cursor.close()


def send_credentials_email(email, username, password):
    """Envoie un email avec les identifiants de connexion"""
    subject = "Vos identifiants de connexion - Tilto"
    
    body = f"""
    Bonjour,

    Votre compte Tilto a été créé avec succès.

    Voici vos identifiants de connexion :
    - Nom d'utilisateur : {username}
    - Mot de passe : {password}

    Pour vous connecter, rendez-vous sur : https://tilto.co/login

    Pour votre sécurité, nous vous recommandons de changer votre mot de passe lors de votre première connexion.

    Cordialement,
    L'équipe Tilto
    """
    
    msg = Message(
        subject=subject,
        recipients=[email],
        body=body
    )
    
    mail.send(msg)


@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Supprime un utilisateur (MySQL CASCADE/SET NULL fait le reste automatiquement)"""
    try:
        # Vérifier que l'admin ne supprime pas son propre compte
        if user_id == current_user.id:
            return jsonify({'success': False, 'message': 'Vous ne pouvez pas supprimer votre propre compte'}), 400
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer les infos de l'utilisateur
        cursor.execute("SELECT username, email, user_status FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            return jsonify({'success': False, 'message': 'Utilisateur introuvable'}), 404
        
        # Empêcher la suppression d'un admin
        if user['user_status'] == 'admin':
            cursor.close()
            return jsonify({'success': False, 'message': 'Impossible de supprimer un administrateur'}), 403
        
        logger.info(f"🗑️ Début suppression utilisateur {user_id} ({user['username']}) par admin {current_user.id}")
        
        # ✅ SUPPRESSION SIMPLE - MySQL CASCADE/SET NULL fait TOUT automatiquement !
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        
        # COMMIT
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Utilisateur {user_id} ({user['username']}) supprimé avec succès")
        
        return jsonify({
            'success': True,
            'message': f"Utilisateur {user['username']} supprimé avec succès",
            'summary': {
                'username': user['username'],
                'email': user['email']
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la suppression de l'utilisateur {user_id}: {str(e)}", exc_info=True)
        if 'mysql' in locals():
            mysql.connection.rollback()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}), 500


@admin_bp.route('/user/<int:user_id>/details', methods=['GET'])
@login_required
@admin_required
def user_details(user_id):
    """
    Affiche toutes les informations détaillées d'un utilisateur.

    L'agrégation est déléguée à `services.user_context_service.UserContextService`
    qui expose la même vue 360° comme un objet Python réutilisable
    (par les agents, les futurs reports, etc.) — pas seulement pour le template admin.
    """
    try:
        from services.user_context_service import UserContextService
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)

        ctx_service = UserContextService(cursor=cursor, user_id=user_id)
        user_data = ctx_service.get_full_context()

        if not user_data:
            cursor.close()
            flash("Utilisateur introuvable", "danger")
            return redirect(url_for('auth.dashboard'))

        cursor.close()
        return render_template('admin/user_details.html', data=user_data)

    except Exception as e:
        logger.error(f"❌ Erreur récupération détails utilisateur: {str(e)}", exc_info=True)
        flash("Erreur lors de la récupération des détails utilisateur", "danger")
        return redirect(url_for('auth.dashboard'))

@admin_bp.route('/user/<int:user_id>/change-status', methods=['POST'])
@login_required
@admin_required
def change_user_status(user_id):
    """Change le statut d'un utilisateur"""
    try:
        data = request.get_json()
        new_status = data.get('new_status')
        
        # Vérifier que l'admin ne modifie pas son propre statut
        if user_id == current_user.id:
            return jsonify({'success': False, 'message': 'Vous ne pouvez pas modifier votre propre statut'}), 400
        
        # Valider le nouveau statut
        valid_statuses = ['lead', 'free_user', 'user', 'admin', 'coach']
        if new_status not in valid_statuses:
            return jsonify({'success': False, 'message': 'Statut invalide'}), 400
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Vérifier que l'utilisateur existe et récupérer l'ancien statut
        cursor.execute("SELECT username, email, user_status FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'success': False, 'message': 'Utilisateur introuvable'}), 404
        
        old_status = user['user_status']
        username = user['username']
        
        # Si c'est le même statut, pas besoin de mettre à jour
        if old_status == new_status:
            return jsonify({'success': True, 'message': 'Le statut est déjà à jour', 'new_status': new_status})
        
        # Empêcher la rétrogradation d'admin à un autre statut (protection supplémentaire)
        if old_status == 'admin' and new_status != 'admin':
            return jsonify({'success': False, 'message': 'Impossible de rétrograder un administrateur. Contactez un super-admin.'}), 403
        
        # Mettre à jour le statut
        cursor.execute("""
            UPDATE users 
            SET user_status = %s, updated_at = %s 
            WHERE user_id = %s
        """, (new_status, datetime.now(), user_id))
        
        mysql.connection.commit()
        cursor.close()
        
        # Logger l'action
        logger.info(f"✅ Statut changé - User: {user_id} ({username}), {old_status} → {new_status}, Par admin: {current_user.id}")
        
        # Déterminer le message et l'icône selon le changement
        status_labels = {
            'lead': '🎯 Lead (Prospect)',
            'free_user': '🆓 Utilisateur gratuit',
            'user': '💳 Client (Payant)',
            'admin': '👑 Administrateur',
            'coach': '🎓 Coach'
        }
        
        message = f"Statut changé : {status_labels.get(old_status, old_status)} → {status_labels.get(new_status, new_status)}"
        
        return jsonify({
            'success': True,
            'message': message,
            'new_status': new_status,
            'old_status': old_status,
            'username': username
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur changement de statut: {str(e)}", exc_info=True)
        mysql.connection.rollback()
        return jsonify({'success': False, 'message': f'Erreur: {str(e)}'}), 500

# ==================== ROUTE PRINCIPALE ====================
# ==================== ROUTE PRINCIPALE ====================
@admin_bp.route('/activity-stats')
@login_required
@admin_required
def admin_activity_stats():
    """Page principale des statistiques d'activité"""
    
    # Récupérer les filtres
    selected_user_id = request.args.get('user_id', type=int)
    period = request.args.get('period', '7days')
    event_type = request.args.get('event_type', '')
    page_path_filter = request.args.get('page_path', '')  # NOUVEAU
    page = request.args.get('page', 1, type=int)
    group_sessions = request.args.get('group_sessions', '0') == '1'
    per_page = 50
    
    # Récupérer les dates personnalisées
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Calculer les dates selon la période
    now = datetime.now()
    if period == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period == '7days':
        start_date = now - timedelta(days=7)
        end_date = now
    elif period == '30days':
        start_date = now - timedelta(days=30)
        end_date = now
    elif period == '90days':
        start_date = now - timedelta(days=90)
        end_date = now
    elif period == 'custom' and date_from:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            if date_to:
                end_date = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            else:
                end_date = now
        except ValueError:
            start_date = now - timedelta(days=7)
            end_date = now
    else:  # 'all'
        start_date = datetime(2020, 1, 1)
        end_date = now
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    # Récupérer la liste des utilisateurs pour le dropdown
    cursor.execute('''
        SELECT user_id, firstname, lastname, email, created_at 
        FROM users 
        ORDER BY firstname
    ''')
    users = cursor.fetchall()
    
    # Récupérer les pages disponibles pour le dropdown (pages uniques)
    cursor.execute('''
        SELECT DISTINCT page_path, COUNT(*) as count
        FROM activity_logs 
        WHERE page_path IS NOT NULL AND created_at >= %s AND created_at <= %s
        GROUP BY page_path
        ORDER BY count DESC
        LIMIT 100
    ''', (start_date, end_date))
    available_pages = cursor.fetchall()
    
    if selected_user_id:
        # ==================== VUE UTILISATEUR SPÉCIFIQUE ====================
        
        # Infos utilisateur
        cursor.execute('''
            SELECT user_id, firstname, lastname, email, created_at 
            FROM users WHERE user_id = %s
        ''', (selected_user_id,))
        user_info = cursor.fetchone()
        
        if not user_info:
            flash('Utilisateur non trouvé', 'warning')
            return redirect(url_for('admin.admin_activity_stats'))
        
        # Construction des filtres pour vue utilisateur
        filters = []
        params_base = [selected_user_id, start_date, end_date]
        
        if event_type:
            filters.append("event_type = %s")
            params_base.append(event_type)
        
        if page_path_filter:
            filters.append("page_path LIKE %s")
            params_base.append(f"%{page_path_filter}%")
        
        extra_filter = " AND " + " AND ".join(filters) if filters else ""
        
        # Stats utilisateur
        cursor.execute(f'''
            SELECT 
                COUNT(*) as total_views,
                MAX(created_at) as last_activity,
                (SELECT device_type FROM activity_logs 
                 WHERE user_id = %s 
                 GROUP BY device_type 
                 ORDER BY COUNT(*) DESC 
                 LIMIT 1) as preferred_device
            FROM activity_logs
            WHERE user_id = %s AND created_at >= %s AND created_at <= %s {extra_filter}
        ''', tuple([selected_user_id] + params_base))
        user_stats = cursor.fetchone() or {}
        
        # Estimer le nombre de sessions (gap > 30 min = nouvelle session)
        cursor.execute(f'''
            SELECT COUNT(*) as sessions_count
            FROM (
                SELECT 
                    created_at,
                    LAG(created_at) OVER (ORDER BY created_at) as prev_time
                FROM activity_logs
                WHERE user_id = %s AND created_at >= %s AND created_at <= %s {extra_filter}
            ) t
            WHERE prev_time IS NULL 
               OR TIMESTAMPDIFF(MINUTE, prev_time, created_at) > 30
        ''', tuple(params_base))
        sessions_result = cursor.fetchone()
        user_stats['sessions_count'] = sessions_result['sessions_count'] if sessions_result else 0
        
        # Compter le total pour la pagination
        cursor.execute(f'''
            SELECT COUNT(*) as total
            FROM activity_logs
            WHERE user_id = %s AND created_at >= %s AND created_at <= %s {extra_filter}
        ''', tuple(params_base))
        total_logs = cursor.fetchone()['total']
        total_pages = (total_logs + per_page - 1) // per_page
        
        offset = (page - 1) * per_page
        params_with_limit = params_base + [per_page, offset]
        
        cursor.execute(f'''
            SELECT id, event_type, page_path, referrer, device_type, extra_data, created_at
            FROM activity_logs
            WHERE user_id = %s AND created_at >= %s AND created_at <= %s {extra_filter}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        ''', tuple(params_with_limit))
        logs = cursor.fetchall()
        
        # Grouper par sessions si demandé
        sessions = []
        if group_sessions and logs:
            current_session = {
                'logs': [],
                'start_time': None,
                'end_time': None
            }
            
            # Inverser pour avoir l'ordre chronologique
            logs_chrono = list(reversed(logs))
            
            for log in logs_chrono:
                if not current_session['logs']:
                    current_session['logs'].append(log)
                    current_session['start_time'] = log['created_at']
                    current_session['end_time'] = log['created_at']
                else:
                    last_time = current_session['end_time']
                    gap = (log['created_at'] - last_time).total_seconds() / 60
                    
                    if gap > 30:  # Nouvelle session si gap > 30 min
                        current_session['page_count'] = len(current_session['logs'])
                        current_session['duration'] = int(
                            (current_session['end_time'] - current_session['start_time']).total_seconds() / 60
                        )
                        sessions.append(current_session)
                        
                        current_session = {
                            'logs': [log],
                            'start_time': log['created_at'],
                            'end_time': log['created_at']
                        }
                    else:
                        current_session['logs'].append(log)
                        current_session['end_time'] = log['created_at']
            
            # Ajouter la dernière session
            if current_session['logs']:
                current_session['page_count'] = len(current_session['logs'])
                current_session['duration'] = int(
                    (current_session['end_time'] - current_session['start_time']).total_seconds() / 60
                )
                sessions.append(current_session)
            
            sessions.reverse()  # Plus récent en premier
        
        # Dernières activités (live feed)
        cursor.execute('''
            SELECT al.*, u.firstname
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.user_id
            ORDER BY al.created_at DESC
            LIMIT 20
        ''')
        recent_logs = cursor.fetchall()
        
        cursor.close()
        
        return render_template('admin/admin_activity_stats.html',
            users=users,
            available_pages=available_pages,
            selected_user_id=selected_user_id,
            period=period,
            event_type=event_type,
            page_path_filter=page_path_filter,
            date_from=date_from,
            date_to=date_to,
            user_info=user_info,
            user_stats=user_stats,
            logs=logs,
            sessions=sessions,
            group_sessions=group_sessions,
            current_page=page,
            total_pages=total_pages,
            recent_logs=recent_logs
        )
    
    else:
        # ==================== VUE GLOBALE ====================
        
        # Construction des filtres
        filters = []
        params = [start_date, end_date]
        
        if event_type:
            filters.append("event_type = %s")
            params.append(event_type)
        
        if page_path_filter:
            filters.append("page_path LIKE %s")
            params.append(f"%{page_path_filter}%")
        
        extra_filter = " AND " + " AND ".join(filters) if filters else ""
        
        # Stats globales
        cursor.execute(f'''
            SELECT 
                COUNT(*) as total_views,
                COUNT(DISTINCT user_id) as active_users,
                ROUND(COUNT(*) / NULLIF(COUNT(DISTINCT user_id), 0), 1) as pages_per_user
            FROM activity_logs
            WHERE created_at >= %s AND created_at <= %s {extra_filter}
        ''', tuple(params))
        stats = cursor.fetchone() or {'total_views': 0, 'active_users': 0, 'pages_per_user': 0}
        
        # Calculer le % mobile
        cursor.execute('''
            SELECT 
                ROUND(SUM(CASE WHEN device_type = 'mobile' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as mobile_percent
            FROM activity_logs
            WHERE created_at >= %s AND created_at <= %s
        ''', (start_date, end_date))
        mobile_result = cursor.fetchone()
        stats['mobile_percent'] = mobile_result['mobile_percent'] if mobile_result and mobile_result['mobile_percent'] else 0
        
        # Top 10 pages (avec le filtre appliqué)
        cursor.execute(f'''
            SELECT 
                page_path,
                COUNT(*) as views,
                ROUND(COUNT(*) * 100.0 / NULLIF((
                    SELECT COUNT(*) FROM activity_logs 
                    WHERE created_at >= %s AND created_at <= %s {extra_filter}
                ), 0), 1) as percent
            FROM activity_logs
            WHERE created_at >= %s AND created_at <= %s {extra_filter}
            GROUP BY page_path
            ORDER BY views DESC
            LIMIT 10
        ''', tuple(params + params))
        top_pages = cursor.fetchall()
        
        # Top 10 utilisateurs
        cursor.execute(f'''
            SELECT 
                al.user_id,
                u.firstname,
                COUNT(*) as page_count
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.user_id
            WHERE al.created_at >= %s AND al.created_at <= %s {extra_filter}
            GROUP BY al.user_id, u.firstname
            ORDER BY page_count DESC
            LIMIT 10
        ''', tuple(params))
        top_users = cursor.fetchall()
        
        # Dernières connexions (utilisateurs uniques avec leur dernière activité)
        cursor.execute(f'''
            SELECT 
                al.user_id,
                u.firstname,
                u.lastname,
                u.email,
                MAX(al.created_at) as last_activity,
                COUNT(*) as page_count,
                (SELECT device_type FROM activity_logs 
                 WHERE user_id = al.user_id 
                 ORDER BY created_at DESC LIMIT 1) as last_device
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.user_id
            WHERE al.created_at >= %s AND al.created_at <= %s {extra_filter}
            GROUP BY al.user_id, u.firstname, u.lastname, u.email
            ORDER BY last_activity DESC
            LIMIT 15
        ''', tuple(params))
        recent_connections = cursor.fetchall()
        
        # Répartition par type d'événement
        cursor.execute(f'''
            SELECT event_type, COUNT(*) as count
            FROM activity_logs
            WHERE created_at >= %s AND created_at <= %s {extra_filter}
            GROUP BY event_type
            ORDER BY count DESC
        ''', tuple(params))
        event_types = cursor.fetchall()
        
        # Données pour le graphique (par jour)
        cursor.execute(f'''
            SELECT 
                DATE(created_at) as day,
                COUNT(*) as views
            FROM activity_logs
            WHERE created_at >= %s AND created_at <= %s {extra_filter}
            GROUP BY DATE(created_at)
            ORDER BY day ASC
        ''', tuple(params))
        daily_data = cursor.fetchall()
        
        # S'assurer que daily_stats contient des données
        if daily_data and len(daily_data) > 0:
            daily_stats = {
                'labels': [d['day'].strftime('%d/%m') for d in daily_data],
                'values': [int(d['views']) for d in daily_data]
            }
            logger.info(f"📊 daily_stats: {len(daily_data)} jours, labels={daily_stats['labels']}, values={daily_stats['values']}")
        else:
            daily_stats = {'labels': [], 'values': []}
            logger.info("📊 daily_stats: Aucune donnée")
        
        # Dernières activités (live feed)
        cursor.execute('''
            SELECT al.*, u.firstname
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.user_id
            ORDER BY al.created_at DESC
            LIMIT 20
        ''')
        recent_logs = cursor.fetchall()
        
        cursor.close()
        
        return render_template('admin/admin_activity_stats.html',
            users=users,
            available_pages=available_pages,
            selected_user_id=None,
            period=period,
            event_type=event_type,
            page_path_filter=page_path_filter,
            date_from=date_from,
            date_to=date_to,
            stats=stats,
            top_pages=top_pages,
            top_users=top_users,
            recent_connections=recent_connections,
            event_types=event_types,
            daily_stats=daily_stats,
            recent_logs=recent_logs
        )
# ==================== ENDPOINT LIVE FEED ====================
@admin_bp.route('/activity-stats/live-feed')
@login_required
@admin_required
def admin_activity_live_feed():
    """API pour rafraîchir le live feed"""
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    cursor.execute('''
        SELECT al.page_path, al.device_type, al.created_at, u.firstname
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.user_id
        ORDER BY al.created_at DESC
        LIMIT 20
    ''')
    logs = cursor.fetchall()
    cursor.close()
    
    # Formater pour le JSON
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            'firstname': log['firstname'],
            'page_path': log['page_path'],
            'device_type': log['device_type'],
            'time': log['created_at'].strftime('%H:%M:%S')
        })
    
    return jsonify({
        'success': True,
        'logs': formatted_logs
    })


# ==================== ENDPOINT EXPORT CSV (bonus) ====================
@admin_bp.route('/activity-stats/export')
@login_required
@admin_required
def admin_activity_export():
    """Exporter les logs en CSV"""
    import csv
    from io import StringIO
    from flask import Response
    
    user_id = request.args.get('user_id', type=int)
    period = request.args.get('period', '7days')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Calculer les dates
    now = datetime.now()
    if period == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif period == '7days':
        start_date = now - timedelta(days=7)
        end_date = now
    elif period == '30days':
        start_date = now - timedelta(days=30)
        end_date = now
    elif period == '90days':
        start_date = now - timedelta(days=90)
        end_date = now
    elif period == 'custom' and date_from:
        try:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            if date_to:
                end_date = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            else:
                end_date = now
        except ValueError:
            start_date = now - timedelta(days=7)
            end_date = now
    else:
        start_date = datetime(2020, 1, 1)
        end_date = now
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    query = '''
        SELECT al.*, u.firstname, u.email
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.user_id
        WHERE al.created_at >= %s AND al.created_at <= %s
    '''
    params = [start_date, end_date]
    
    if user_id:
        query += ' AND al.user_id = %s'
        params.append(user_id)
    
    query += ' ORDER BY al.created_at DESC LIMIT 10000'
    
    cursor.execute(query, tuple(params))
    logs = cursor.fetchall()
    cursor.close()
    
    # Créer le CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # En-têtes
    writer.writerow(['Date', 'Heure', 'User ID', 'Prénom', 'Email', 'Event', 'Page', 'Device', 'Referrer'])
    
    for log in logs:
        writer.writerow([
            log['created_at'].strftime('%Y-%m-%d'),
            log['created_at'].strftime('%H:%M:%S'),
            log['user_id'],
            log['firstname'],
            log['email'],
            log['event_type'],
            log['page_path'],
            log['device_type'],
            log['referrer'] or ''
        ])
    
    output.seek(0)
    
    filename = f"activity_logs_{period}"
    if user_id:
        filename += f"_user_{user_id}"
    filename += f"_{now.strftime('%Y%m%d')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@admin_bp.route('/user/<int:user_id>/tokens')
@login_required
@admin_required
def get_user_tokens(user_id):
    """Récupérer tous les tokens d'un utilisateur (consommés ou non)"""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        cursor.execute("""
            SELECT token_code, token_type, description, 
                   used_at,
                   used_for_piste,
                   DATE_FORMAT(expiration_date, '%%d/%%m/%%Y') as expiration_date,
                   DATE_FORMAT(created_at, '%%d/%%m/%%Y') as created_at,
                   DATE_FORMAT(used_at, '%%d/%%m/%%Y à %%H:%%i') as used_at_formatted,
                   CASE 
                       WHEN used_at IS NOT NULL THEN 'used'
                       WHEN expiration_date IS NOT NULL AND expiration_date < NOW() THEN 'expired'
                       ELSE 'available'
                   END as status
            FROM tokens 
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        
        tokens = cursor.fetchall()
        cursor.close()
        
        # Compter les stats
        stats = {
            'total': len(tokens),
            'available': len([t for t in tokens if t['status'] == 'available']),
            'used': len([t for t in tokens if t['status'] == 'used']),
            'expired': len([t for t in tokens if t['status'] == 'expired'])
        }
        
        return jsonify({'success': True, 'tokens': tokens, 'stats': stats})
    except Exception as e:
        logger.error(f"Erreur récupération tokens user {user_id}: {e}")
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/user/<int:user_id>/tokens/add', methods=['POST'])
@login_required
@admin_required
def add_user_token(user_id):
    """Ajouter un token offert à un utilisateur"""
    try:
        data = request.get_json()
        expiration_date = data.get('expiration_date')
        description = data.get('description', 'Credit offert par admin')
        
        # Générer un code unique
        token_code = f"GIFT_{secrets.token_hex(6).upper()}"
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        cursor.execute("""
            INSERT INTO tokens (token_code, user_id, quiz_id, token_type, description, expiration_date, created_at)
            VALUES (%s, %s, 'pack_clarte', 'free', %s, %s, NOW())
        """, (token_code, user_id, description, expiration_date))
        
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Token {token_code} ajouté pour user {user_id} par admin {current_user.id}")
        
        return jsonify({
            'success': True, 
            'message': f'Crédit {token_code} ajouté',
            'token_code': token_code
        })
    except Exception as e:
        logger.error(f"Erreur ajout token user {user_id}: {e}")
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/user/<int:user_id>/tokens/<token_code>/mark-used', methods=['POST'])
@login_required
@admin_required
def mark_token_used(user_id, token_code):
    """Marquer un token comme utilisé manuellement"""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Vérifier que le token existe et n'est pas déjà utilisé
        cursor.execute("""
            SELECT token_code, used_at 
            FROM tokens 
            WHERE token_code = %s AND user_id = %s
        """, (token_code, user_id))
        
        token = cursor.fetchone()
        
        if not token:
            cursor.close()
            return jsonify({'success': False, 'message': 'Token non trouvé'}), 404
        
        if token['used_at'] is not None:
            cursor.close()
            return jsonify({'success': False, 'message': 'Ce token est déjà utilisé'}), 400
        
        # Marquer comme utilisé (used_for_piste = NULL car marquage manuel admin)
        cursor.execute("""
            UPDATE tokens 
            SET used_at = NOW(),
                is_used = TRUE,
                used_for_piste = NULL
            WHERE token_code = %s AND user_id = %s
        """, (token_code, user_id))
        
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Token {token_code} marqué utilisé manuellement pour user {user_id} par admin {current_user.id}")
        
        return jsonify({
            'success': True, 
            'message': f'Crédit {token_code} marqué comme utilisé'
        })
        
    except Exception as e:
        logger.error(f"Erreur marquage token {token_code} user {user_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/user/<int:user_id>/tokens/<token_code>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user_token(user_id, token_code):
    """Supprimer un token d'un utilisateur"""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        cursor.execute("""
            DELETE FROM tokens 
            WHERE token_code = %s AND user_id = %s AND used_at IS NULL
        """, (token_code, user_id))
        
        if cursor.rowcount == 0:
            cursor.close()
            return jsonify({'success': False, 'message': 'Token non trouvé ou déjà utilisé'})
        
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"🗑️ Token {token_code} supprimé pour user {user_id} par admin {current_user.id}")
        
        return jsonify({'success': True, 'message': 'Crédit supprimé'})
    except Exception as e:
        logger.error(f"Erreur suppression token {token_code} user {user_id}: {e}")
        return jsonify({'success': False, 'message': str(e)})
