from flask import Blueprint, request, jsonify, current_app, g, render_template
from flask_login import current_user, login_required
from extensions import mysql, limiter  # ✅ AJOUT : Import du limiter
from functools import wraps
import logging
import json
from datetime import datetime
from decorators import admin_required
import re

logger = logging.getLogger('chat_bp')

chat_bp = Blueprint('chat', __name__, url_prefix='/api')


# ==================== VALIDATION & SÉCURITÉ ====================

def is_valid_email(email):
    """Validation stricte de l'email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) and len(email) <= 255

def sanitize_input(text, max_length=500):
    """Nettoie et limite la longueur du texte"""
    if not text:
        return ""
    # Retirer les caractères de contrôle dangereux
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    # Limiter la longueur
    return text[:max_length].strip()


# ==================== ENDPOINT PUBLIC : RECEVOIR MESSAGE ====================
@chat_bp.route('/chat-message', methods=['POST'])
@limiter.limit("3 per minute")  # ✅ MAX 3 messages par minute par IP
@limiter.limit("10 per hour")   # ✅ MAX 10 messages par heure par IP
@limiter.limit("20 per day")    # ✅ MAX 20 messages par jour par IP
def receive_chat_message():
    """Endpoint pour recevoir les messages du chat widget - SÉCURISÉ"""
    try:
        request_id = getattr(g, 'request_id', 'unknown')
        logger.info(f"[{request_id}] 💬 Réception message chat depuis IP: {request.remote_addr}")
        
        # ✅ HONEYPOT : Champ invisible pour piéger les bots
        honeypot = request.form.get('website', '').strip()
        if honeypot:
            logger.warning(f"[{request_id}] 🤖 BOT DÉTECTÉ (honeypot rempli) - IP: {request.remote_addr}")
            # Faire semblant que ça a marché pour tromper le bot
            return jsonify({'success': True, 'message': 'Message envoyé avec succès'}), 200
        
        # Récupérer les données
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()
        context_str = request.form.get('context', '{}')
        
        # ✅ VALIDATION EMAIL STRICTE
        if not email or not is_valid_email(email):
            return jsonify({'success': False, 'error': 'Email invalide'}), 400
        
        # ✅ SANITIZATION + VALIDATION MESSAGE
        message = sanitize_input(message, max_length=500)
        
        if not message:
            return jsonify({'success': False, 'error': 'Message requis'}), 400
            
        if len(message) < 10:
            return jsonify({'success': False, 'error': 'Message trop court (minimum 10 caractères)'}), 400
        
        # ✅ VALIDATION CONTEXT JSON
        try:
            context = json.loads(context_str)
            # Limiter la taille du context
            if len(json.dumps(context)) > 2000:
                context = {'page': context.get('page', 'N/A')[:200]}
        except:
            context = {}

        # ✅ DÉTECTION SPAM : Vérifier si l'email a déjà envoyé trop de messages récemment
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT COUNT(*) 
            FROM chat_messages 
            WHERE email = %s 
            AND created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)
        """, (email,))
        recent_count = cursor.fetchone()[0]
        
        if recent_count >= 5:
            cursor.close()
            logger.warning(f"[{request_id}] ⚠️ SPAM DÉTECTÉ - Email {email} a envoyé {recent_count} messages en 1h")
            return jsonify({
                'success': False, 
                'error': 'Trop de messages envoyés. Veuillez patienter avant de réessayer.'
            }), 429

        # Informations utilisateur
        user_id = current_user.id if current_user.is_authenticated else None
        user_name = current_user.username if current_user.is_authenticated else email.split('@')[0]
        firstname = user_name.split()[0] if user_name else "Utilisateur"

        # Sauvegarder en BDD
        cursor.execute("""
            INSERT INTO chat_messages 
            (user_id, email, message, context, created_at, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        """, (
            user_id,
            email,
            message,
            json.dumps(context),
            datetime.now()
        ))
        message_id = cursor.lastrowid
        mysql.connection.commit()
        cursor.close()

        logger.info(f"[{request_id}] ✅ Message chat #{message_id} sauvegardé pour {email}")

        # Envoyer notification Slack
        try:
            from services.slack_service import slack_service
            
            slack_message = (
                f"💬 *Nouveau message chat*\n\n"
                f"👤 *De:* {user_name}\n\n"
                f"📧 *Email:* {email}\n\n"
                f"📍 *Page:* {context.get('page', 'N/A')}\n\n"
                f"💬 *Message:*\n{message}\n\n"
                f"🆔 ID: {message_id} | User: {user_id or 'Anonyme'}\n\n"
                f"⏰ {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
            )
            
            slack_result = slack_service.send_notification(
                slack_message,
                channel='chat'
            )
            
            if slack_result:
                logger.info(f"[{request_id}] ✅ Notification Slack envoyée pour message #{message_id}")
            else:
                logger.warning(f"[{request_id}] ⚠️ Échec notification Slack pour message #{message_id}")
                
        except Exception as slack_error:
            logger.error(f"[{request_id}] ❌ Erreur envoi Slack: {slack_error}")

        # Envoyer email de confirmation à l'utilisateur
        try:
            from services.email_service import send_email
            
            html_content = render_template(
                'emails/chat_confirmation.html',
                firstname=firstname,
                message=message,
                current_user=current_user
            )
            
            text_content = render_template(
                'emails/chat_confirmation.txt',
                firstname=firstname,
                message=message,
                current_user=current_user
            )
            
            email_result = send_email(
                to_email=email,
                subject="On a bien reçu ton message ! 💬 - Tilto",
                html_content=html_content,
                text_content=text_content
            )
            
            if email_result.get('success'):
                logger.info(f"[{request_id}] ✅ Email de confirmation envoyé à {email}")
            else:
                logger.error(f"[{request_id}] ❌ Échec envoi email: {email_result.get('message')}")
                
        except Exception as email_error:
            logger.error(f"[{request_id}] ❌ Erreur envoi email: {email_error}")

        return jsonify({
            'success': True,
            'message': 'Message envoyé avec succès',
            'message_id': message_id
        }), 200

    except Exception as e:
        logger.error(f"❌ Erreur traitement message chat: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Erreur serveur. Réessaye ou écris-nous à contact@tilto.ai'
        }), 500


# ==================== ENDPOINTS ADMIN ====================

@chat_bp.route('/chat-messages', methods=['GET'])
@admin_required
def get_chat_messages():
    """Page d'administration des messages du chat widget"""
    try:
        request_id = getattr(g, 'request_id', 'unknown')
        logger.info(f"[{request_id}] 📬 Accès admin chat messages")
        
        # Filtres
        status_filter = request.args.get('status', 'all')
        
        # Récupérer tous les messages
        cursor = mysql.connection.cursor()
        
        query = """
            SELECT 
                cm.id,
                cm.user_id,
                cm.email,
                cm.message,
                cm.context,
                cm.status,
                cm.replied_at,
                cm.replied_by,
                cm.notes,
                cm.created_at,
                u.username
            FROM chat_messages cm
            LEFT JOIN users u ON cm.user_id = u.user_id
        """
        
        if status_filter != 'all':
            query += f" WHERE cm.status = '{status_filter}'"
        
        query += " ORDER BY cm.created_at DESC"
        
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        
        # 🔧 MODIFICATION : Parser le JSON context côté Python
        messages = []
        for row in cursor.fetchall():
            msg = dict(zip(columns, row))
            # Parser le JSON context si présent
            if msg.get('context'):
                try:
                    # MySQL peut retourner soit une string JSON, soit déjà un dict
                    msg['context_data'] = json.loads(msg['context']) if isinstance(msg['context'], str) else msg['context']
                except Exception as e:
                    logger.warning(f"Erreur parsing context JSON pour message #{msg.get('id')}: {e}")
                    msg['context_data'] = {}
            else:
                msg['context_data'] = {}
            messages.append(msg)
        
        # Statistiques
        cursor.execute("SELECT COUNT(*) as total FROM chat_messages")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) as pending FROM chat_messages WHERE status = 'pending'")
        pending = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) as replied FROM chat_messages WHERE status = 'replied'")
        replied = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) as archived FROM chat_messages WHERE status = 'archived'")
        archived = cursor.fetchone()[0]
        
        cursor.close()
        
        stats = {
            'total': total,
            'pending': pending,
            'replied': replied,
            'archived': archived
        }
        
        return render_template(
            'admin/chat_messages.html',
            messages=messages,
            stats=stats,
            status_filter=status_filter
        )
        
    except Exception as e:
        logger.error(f"❌ Erreur admin chat: {e}", exc_info=True)
        return render_template('errors/500.html'), 500


@chat_bp.route('/chat-messages/mark-replied', methods=['POST'])
@admin_required
def mark_replied():
    """Marquer un message comme répondu"""
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        notes = data.get('notes', '')
        
        if not message_id:
            return jsonify({'success': False, 'error': 'ID manquant'}), 400
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE chat_messages 
            SET status = 'replied',
                replied_at = %s,
                replied_by = %s,
                notes = %s
            WHERE id = %s
        """, (datetime.now(), current_user.id, notes, message_id))
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Message #{message_id} marqué comme répondu par {current_user.username}")
        
        return jsonify({'success': True, 'message': 'Message marqué comme répondu'})
        
    except Exception as e:
        logger.error(f"❌ Erreur mark_replied: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_bp.route('/chat-messages/archive', methods=['POST'])
@admin_required
def archive_message():
    """Archiver un message"""
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        
        if not message_id:
            return jsonify({'success': False, 'error': 'ID manquant'}), 400
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE chat_messages 
            SET status = 'archived'
            WHERE id = %s
        """, (message_id,))
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"🗄️ Message #{message_id} archivé par {current_user.username}")
        
        return jsonify({'success': True, 'message': 'Message archivé'})
        
    except Exception as e:
        logger.error(f"❌ Erreur archive: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_bp.route('/chat-messages/add-note', methods=['POST'])
@admin_required
def add_note():
    """Ajouter une note interne à un message"""
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        notes = data.get('notes', '')
        
        if not message_id:
            return jsonify({'success': False, 'error': 'ID manquant'}), 400
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE chat_messages 
            SET notes = %s
            WHERE id = %s
        """, (notes, message_id))
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"📝 Note ajoutée au message #{message_id} par {current_user.username}")
        
        return jsonify({'success': True, 'message': 'Note ajoutée'})
        
    except Exception as e:
        logger.error(f"❌ Erreur add_note: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@chat_bp.route('/chat-messages/delete', methods=['POST'])
@admin_required
def delete_message():
    """Supprimer un message"""
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        
        if not message_id:
            return jsonify({'success': False, 'error': 'ID manquant'}), 400
        
        cursor = mysql.connection.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE id = %s", (message_id,))
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"🗑️ Message #{message_id} supprimé par {current_user.username}")
        
        return jsonify({'success': True, 'message': 'Message supprimé'})
        
    except Exception as e:
        logger.error(f"❌ Erreur delete: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@chat_bp.route('/chat-messages/send-reply', methods=['POST'])
@admin_required
def send_reply():
    """Envoyer une réponse par email à un utilisateur"""
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        recipient_email = data.get('recipient_email')
        recipient_name = data.get('recipient_name')
        original_message = data.get('original_message')
        reply_text = data.get('reply_text')
        
        if not all([message_id, recipient_email, reply_text]):
            return jsonify({'success': False, 'error': 'Données manquantes'}), 400
        
        # Préparer le prénom
        firstname = recipient_name.split()[0] if recipient_name else recipient_email.split('@')[0]
        
        # Envoyer l'email de réponse
        try:
            from services.email_service import send_email
            
            html_content = render_template(
                'emails/admin_reply.html',
                firstname=firstname,
                original_message=original_message,
                admin_reply=reply_text.replace('\n', '<br>'),
                admin_name=current_user.username
            )
            
            text_content = f"""Hello {firstname},

Tu nous avais écrit :
"{original_message}"

Voici notre réponse :
{reply_text}


"""
            
            email_result = send_email(
                to_email=recipient_email,
                subject="Réponse à ta question - Tilto",
                html_content=html_content,
                text_content=text_content
            )
            
            if not email_result.get('success'):
                return jsonify({'success': False, 'error': 'Échec envoi email'}), 500
                
        except Exception as email_error:
            logger.error(f"❌ Erreur envoi email: {email_error}")
            return jsonify({'success': False, 'error': 'Erreur envoi email'}), 500
        
        # Marquer comme répondu
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE chat_messages 
            SET status = 'replied',
                replied_at = %s,
                replied_by = %s,
                notes = CONCAT(COALESCE(notes, ''), '\n\n[Réponse envoyée le ', %s, ']\n', %s)
            WHERE id = %s
        """, (
            datetime.now(),
            current_user.id,
            datetime.now().strftime('%d/%m/%Y à %H:%M'),
            reply_text[:500],  # Extrait de la réponse dans les notes
            message_id
        ))
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Réponse envoyée pour message #{message_id} à {recipient_email}")
        
        return jsonify({'success': True, 'message': 'Réponse envoyée avec succès'})
        
    except Exception as e:
        logger.error(f"❌ Erreur send_reply: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@chat_bp.route('/chat-messages/security-log', methods=['GET'])
@admin_required
def security_log():
    """Voir les tentatives de spam détectées"""
    try:
        cursor = mysql.connection.cursor()
        
        # Messages suspects (email avec trop de messages)
        cursor.execute("""
            SELECT 
                email,
                COUNT(*) as count,
                MAX(created_at) as last_attempt
            FROM chat_messages
            WHERE created_at > DATE_SUB(NOW(), INTERVAL 24 HOURS)
            GROUP BY email
            HAVING count > 5
            ORDER BY count DESC
        """)
        
        suspicious = cursor.fetchall()
        cursor.close()
        
        return jsonify({
            'suspicious_emails': [
                {
                    'email': row[0],
                    'count': row[1],
                    'last_attempt': row[2].isoformat() if row[2] else None
                }
                for row in suspicious
            ]
        })
        
    except Exception as e:
        logger.error(f"Erreur security log: {e}")
        return jsonify({'error': str(e)}), 500

@chat_bp.route('/chat-messages/security-stats', methods=['GET'])
@admin_required
def get_security_stats():
    """Statistiques de sécurité pour l'interface admin"""
    try:
        cursor = mysql.connection.cursor()
        
        # Emails suspects (plus de 5 messages en 1h)
        cursor.execute("""
            SELECT 
                email,
                COUNT(*) as count,
                MAX(created_at) as last_attempt
            FROM chat_messages
            WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)
            GROUP BY email
            HAVING count > 5
            ORDER BY count DESC
            LIMIT 20
        """)
        suspicious_emails = [
            {
                'email': row[0],
                'count': row[1],
                'last_attempt': row[2].isoformat() if row[2] else None
            }
            for row in cursor.fetchall()
        ]
        
        # Messages aujourd'hui
        cursor.execute("""
            SELECT COUNT(*) 
            FROM chat_messages 
            WHERE DATE(created_at) = CURDATE()
        """)
        messages_today = cursor.fetchone()[0]
        
        # Messages dernière heure
        cursor.execute("""
            SELECT COUNT(*) 
            FROM chat_messages 
            WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)
        """)
        messages_last_hour = cursor.fetchone()[0]
        
        cursor.close()
        
        return jsonify({
            'suspicious_emails': suspicious_emails,
            'rate_limited_ips': [],  # Peut être étendu avec Redis si besoin
            'messages_today': messages_today,
            'messages_last_hour': messages_last_hour
        })
        
    except Exception as e:
        logger.error(f"Erreur security stats: {e}")
        return jsonify({'error': str(e)}), 500