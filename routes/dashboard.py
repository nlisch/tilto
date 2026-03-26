"""
Blueprint pour la gestion du dashboard utilisateur et des produits achetés.
Gère l'expérience post-achat avec intégration YouCanBookMe optimisée.
Version 2.0 - Optimisée et moderne
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash, g, jsonify, current_app, send_file, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import logging
import os
import hashlib
import time
import json
from extensions import csrf
from MySQLdb.cursors import DictCursor
from decorators import admin_required
from datetime import datetime, timedelta 
from utils import generate_request_id
import re


logger = logging.getLogger(__name__)

# Configuration du blueprint et logging
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')
logger = logging.getLogger('dashboard_bp')

# Configuration des statuts de commande
ORDER_STATUSES = {
    'achat_confirmé': {'label': '📦 Nouveau', 'color': 'blue', 'description': 'Commande confirmée'},
    'rdv_planifié': {'label': '📅 RDV planifié', 'color': 'purple', 'description': 'Rendez-vous programmé'},
    'analyse_en_cours': {'label': '🔍 En analyse', 'color': 'orange', 'description': 'Analyse en cours'},
    'livrable_dispo': {'label': '✅ Prêt', 'color': 'green', 'description': 'Livrable disponible'},
    'post_livraison': {'label': '🎉 Terminé', 'color': 'gray', 'description': 'Processus terminé'}
}

# Configuration YouCanBookMe
YCBM_EVENTS = {
    'CREATE': ['booking.created', 'booking.confirmed', 'new_booking'],
    'CANCEL': ['booking.cancelled', 'booking_cancelled'],
    'RESCHEDULE': ['booking.rescheduled', 'booking_rescheduled']
}

# === MIDDLEWARES === #

@dashboard_bp.url_defaults
def add_product_id(endpoint, values):
    """Ajoute automatiquement product_id aux URLs si présent dans la vue."""
    if 'product_id' not in values and request.view_args and 'product_id' in request.view_args:
        values['product_id'] = request.view_args['product_id']

@dashboard_bp.url_value_preprocessor
def pull_product_id(endpoint, values):
    """Extrait product_id des URLs et le rend disponible pour la vue."""
    g.product_id = None
    if values and 'product_id' in values:
        g.product_id = values['product_id']

# === FILTRES POUR TEMPLATES === #

@dashboard_bp.app_template_filter('format_date_fr')
def format_date_filter(date):
    """Formate une date en français pour affichage dans les templates."""
    return format_date_fr(date)

@dashboard_bp.app_template_filter('status_label')
def status_label_filter(status):
    """Convertit un code de statut technique en libellé utilisateur avec emoji."""
    return ORDER_STATUSES.get(status, {'label': status}).get('label', status)

@dashboard_bp.app_template_filter('status_color')
def status_color_filter(status):
    """Retourne la couleur associée à un statut."""
    return ORDER_STATUSES.get(status, {'color': 'gray'}).get('color', 'gray')

    # === FONCTIONS UTILITAIRES OPTIMISÉES === #

def format_date_fr(date):
    """Formate une date en français avec gestion d'erreurs robuste."""
    if not date:
        return ""
    try:
        if isinstance(date, str):
            # Essayer différents formats de date
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%Y %H:%M']:
                try:
                    date = datetime.strptime(date, fmt)
                    break
                except ValueError:
                    continue
            else:
                return str(date)  # Si aucun format ne fonctionne
        
        return date.strftime('%d/%m/%Y à %Hh%M')
    except Exception as e:
        logger.error(f"Erreur formatage date: {str(e)}")
        return str(date)

def add_business_days(date, days):
    """Ajoute un nombre de jours ouvrés à une date (exclut weekends)."""
    if not date or not isinstance(date, datetime):
        return None
        
    business_days_to_add = days
    current_date = date
    
    while business_days_to_add > 0:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:  # Lundi=0, Vendredi=4
            business_days_to_add -= 1
    
    return current_date

def generate_share_token(user_id, product_id):
    """Génère un token unique et sécurisé pour le partage."""
    token_base = f"{user_id}_{product_id}_{time.time()}_{os.urandom(16).hex()}"
    return hashlib.sha256(token_base.encode()).hexdigest()[:32]

def extract_user_id_from_webhook(webhook_data):
    """
    Extrait l'user_id depuis les données webhook YCBM.
    Essaie plusieurs sources dans l'ordre de priorité.
    """
    user_id = None
    
    # Option 1: Champs de formulaire (Passthrough questions)
    form_fields = webhook_data.get('formFields', [])
    for field in form_fields:
        field_name = field.get('name', '').lower().replace(' ', '_')
        if any(keyword in field_name for keyword in ['user_id', 'userid', 'client_id']):
            user_id = field.get('value')
            logger.info(f"User ID trouvé dans formFields[{field.get('name')}]: {user_id}")
            break
    
    # Option 2: Réponses directes
    if not user_id:
        answers = webhook_data.get('answers', {})
        for key in ['user_id', 'User ID', 'client_id', 'Client ID']:
            if key in answers:
                user_id = answers[key]
                logger.info(f"User ID trouvé dans answers[{key}]: {user_id}")
                break
    
    # Option 3: Données de niveau racine
    if not user_id:
        user_id = webhook_data.get('user_id')
        if user_id:
            logger.info(f"User ID trouvé directement: {user_id}")
    
    # Option 4: Fallback par email
    if not user_id:
        attendee_email = extract_attendee_email(webhook_data)
        if attendee_email:
            user_id = find_user_by_email(attendee_email)
            if user_id:
                logger.info(f"User ID trouvé par email {attendee_email}: {user_id}")
    
    return user_id

def extract_attendee_email(webhook_data):
    """Extrait l'email du participant depuis les données webhook."""
    return (
        webhook_data.get('email') or 
        webhook_data.get('answers', {}).get('email') or
        webhook_data.get('profile', {}).get('email') or
        webhook_data.get('attendeeEmail')
    )

def extract_attendee_name(webhook_data):
    """Extrait le nom du participant depuis les données webhook."""
    # Nom complet
    full_name = (
        webhook_data.get('name') or
        webhook_data.get('answers', {}).get('name') or
        webhook_data.get('profile', {}).get('name')
    )
    
    if full_name:
        return full_name
    
    # Prénom + Nom
    first_name = (
        webhook_data.get('firstName') or 
        webhook_data.get('answers', {}).get('firstName') or
        webhook_data.get('profile', {}).get('firstName')
    )
    
    last_name = (
        webhook_data.get('lastName') or 
        webhook_data.get('answers', {}).get('lastName') or
        webhook_data.get('profile', {}).get('lastName')
    )
    
    if first_name and last_name:
        return f"{first_name} {last_name}"
    elif first_name:
        return first_name
    
    return None

def find_user_by_email(email):
    """Trouve un utilisateur par son email."""
    if not email:
        return None
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('SELECT user_id FROM users WHERE email = %s LIMIT 1', (email,))
        result = cursor.fetchone()
        return result['user_id'] if result else None
    except Exception as e:
        logger.error(f"Erreur recherche utilisateur par email: {str(e)}")
        return None
    finally:
        cursor.close()

def validate_user_product_access(user_id, product_id):
    """
    Vérifie qu'un utilisateur a bien acheté un produit.
    Retourne True si l'accès est autorisé.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
        ''', (user_id, product_id))
        
        result = cursor.fetchone()
        return result and result['count'] > 0
        
    except Exception as e:
        logger.error(f"Erreur validation accès produit: {str(e)}")
        return False
    finally:
        cursor.close()

def ensure_table_exists(table_name, create_sql):
    """
    S'assure qu'une table existe, la crée si nécessaire.
    Fonction utilitaire pour éviter la répétition de code.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
        if not cursor.fetchone():
            logger.info(f"Création de la table {table_name}")
            cursor.execute(create_sql)
            mysql.connection.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Erreur création table {table_name}: {str(e)}")
        mysql.connection.rollback()
        raise e
    finally:
        cursor.close()
# === GESTION DES STATUTS ET RÉSERVATIONS === #

def get_user_product_status(user_id, product_id):
    """Version corrigée : récupère le statut d'un produit pour un utilisateur."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Requête corrigée pour récupérer AUSSI image_url
        cursor.execute('''
            SELECT 
                ps.id, ps.status, ps.livrable_date, ps.created_at, ps.updated_at,
                ps.booking_id, ps.order_id,
                pc.product_name, pc.subtitle as description, 
                pc.emoji, pc.image_url,  -- ✅ CORRECTION: Récupérer les deux
                b.booking_id as external_booking_id, b.booking_date, b.zoom_link
            FROM product_status ps
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            LEFT JOIN bookings b ON ps.booking_id = b.id
            WHERE ps.user_id = %s AND ps.product_id = %s
            ORDER BY ps.updated_at DESC
            LIMIT 1
        ''', (user_id, product_id))
        
        result = cursor.fetchone()
        
        if result:
            # ✅ CORRECTION: Prioriser image_url, fallback sur emoji
            display_image = result['image_url'] or result['emoji'] or '📦'
            
            result_dict = dict(result)
            result_dict['image_url'] = display_image  # Uniformiser
            return result_dict
        
        # Si aucun statut n'existe, vérifier si l'utilisateur a acheté ce produit
        cursor.execute('''
            SELECT o.order_id, pc.product_name, pc.subtitle as description, 
                   pc.emoji, pc.image_url  -- ✅ Récupérer aussi image_url
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            JOIN product_catalog pc ON op.product_id = pc.product_id
            WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
            LIMIT 1
        ''', (user_id, product_id))
        
        order_result = cursor.fetchone()
        if order_result:
            # ✅ CORRECTION: Même logique de priorisation
            display_image = order_result['image_url'] or order_result['emoji'] or '📦'
            
            # L'utilisateur a acheté ce produit mais n'a pas encore de statut
            cursor.execute('''
                INSERT INTO product_status (user_id, order_id, product_id, status)
                VALUES (%s, %s, %s, 'achat_confirmé')
            ''', (user_id, order_result['order_id'], product_id))
            
            mysql.connection.commit()
            
            return {
                'id': cursor.lastrowid,
                'status': 'achat_confirmé',
                'livrable_date': None,
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'booking_id': None,
                'order_id': order_result['order_id'],
                'product_name': order_result['product_name'],
                'description': order_result['description'],
                'image_url': display_image,  # ✅ CORRECTION
                'external_booking_id': None,
                'booking_date': None,
                'zoom_link': None
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Erreur récupération statut produit: {str(e)}")
        return None
    finally:
        cursor.close()


def update_user_product_status(user_id, product_id, status, booking_id=None, 
                              livrable_date=None, admin_id=None, admin_note=None, 
                              update_type='auto', order_id=None):
    """
    Version corrigée : met à jour le statut d'un produit pour un utilisateur.
    CORRECTION : Signature cohérente avec l'utilisation dans le code.
    """
    logger.info(f"Mise à jour statut - user_id: {user_id}, product_id: {product_id}, status: {status}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        mysql.connection.begin()
        
        # Si order_id n'est pas fourni, essayer de le trouver
        if not order_id:
            cursor.execute('''
                SELECT o.order_id
                FROM orders o
                JOIN order_product op ON o.order_id = op.order_id
                WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
                ORDER BY o.created_at DESC
                LIMIT 1
            ''', (user_id, product_id))
            
            order_result = cursor.fetchone()
            if order_result:
                order_id = order_result['order_id']
            else:
                logger.error(f"Aucune commande trouvée pour user {user_id}, product {product_id}")
                return None
        
        # Récupérer le statut existant
        cursor.execute('''
            SELECT id, status, booking_id 
            FROM product_status 
            WHERE user_id = %s AND product_id = %s
        ''', (user_id, product_id))
        
        existing = cursor.fetchone()
        
        if existing:
            old_status = existing['status']
            status_id = existing['id']
            
            # Mise à jour
            cursor.execute('''
                UPDATE product_status
                SET status = %s, booking_id = %s, livrable_date = %s, updated_at = NOW()
                WHERE id = %s
            ''', (status, booking_id, livrable_date, status_id))
            
        else:
            old_status = None
            
            # Création
            cursor.execute('''
                INSERT INTO product_status 
                (user_id, order_id, product_id, status, booking_id, livrable_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (user_id, order_id, product_id, status, booking_id, livrable_date))
            
            status_id = cursor.lastrowid
        
        # Enregistrer dans l'historique si la table existe
        try:
            cursor.execute('''
                INSERT INTO product_status_updates
                (order_id, user_id, product_id, old_status, new_status, 
                 booking_id, admin_id, admin_note, update_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (status_id, user_id, product_id, old_status, status, 
                  booking_id, admin_id, admin_note, update_type))
        except Exception as hist_error:
            # Si la table d'historique n'existe pas, continuer sans erreur
            logger.warning(f"Impossible d'enregistrer l'historique: {str(hist_error)}")
        
        mysql.connection.commit()
        logger.info(f"✅ Statut mis à jour avec succès: {old_status} → {status}")
        return status_id
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"❌ Erreur mise à jour statut: {str(e)}", exc_info=True)
        return None
    finally:
        cursor.close()

def create_or_update_booking(user_id, product_id, external_booking_id, start_datetime, 
                           end_datetime=None, duration=60, attendee_email=None, 
                           attendee_name=None, answers=None, zoom_link=None):
    """Version corrigée qui gère mieux les erreurs."""
    logger.info(f"🔨 Création booking - User: {user_id}, Product: {product_id}, ID: {external_booking_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        mysql.connection.begin()
        
        # S'assurer que les tables existent
        _ensure_bookings_table_exists()
        
        # Calculer la durée si end_datetime fourni
        if end_datetime and start_datetime:
            duration = int((end_datetime - start_datetime).total_seconds() / 60)
        
        # ✅ UPSERT amélioré
        cursor.execute('''
            INSERT INTO bookings 
            (booking_id, user_id, product_id, booking_date, end_date, 
             duration_minutes, attendee_email, attendee_name, booking_answers, 
             status, zoom_link)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', %s)
            ON DUPLICATE KEY UPDATE
                booking_date = VALUES(booking_date),
                end_date = VALUES(end_date),
                duration_minutes = VALUES(duration_minutes),
                attendee_email = VALUES(attendee_email),
                attendee_name = VALUES(attendee_name),
                booking_answers = VALUES(booking_answers),
                status = 'confirmed',
                zoom_link = VALUES(zoom_link),
                updated_at = NOW()
        ''', (
            external_booking_id, user_id, product_id, start_datetime, end_datetime,
            duration, attendee_email, attendee_name, 
            json.dumps(answers) if answers else None, zoom_link
        ))
        
        # Récupérer l'ID interne
        cursor.execute('SELECT id FROM bookings WHERE booking_id = %s', (external_booking_id,))
        result = cursor.fetchone()
        
        if not result:
            logger.error(f"Impossible de récupérer booking {external_booking_id}")
            return None
        
        booking_db_id = result['id']
        logger.info(f"✅ Booking DB ID: {booking_db_id}")
        
        # ✅ Mise à jour du statut produit
        livrable_date = add_business_days(start_datetime, 3)
        
        # Trouver l'order_id le plus récent
        cursor.execute('''
            SELECT o.order_id
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
            ORDER BY o.created_at DESC
            LIMIT 1
        ''', (user_id, product_id))
        
        order_result = cursor.fetchone()
        if not order_result:
            logger.error(f"Aucune commande trouvée pour user {user_id}, product {product_id}")
            return None
            
        order_id = order_result['order_id']
        
        # Mettre à jour le statut
        success = update_user_product_status(
            user_id=user_id,
            product_id=product_id,
            status="rdv_planifié",
            booking_id=booking_db_id,
            livrable_date=livrable_date,
            admin_note=f"RDV confirmé - ID: {external_booking_id}",
            order_id=order_id
        )
        
        if success:
            mysql.connection.commit()
            logger.info(f"✅ Statut mis à jour vers rdv_planifié")
            return booking_db_id
        else:
            logger.error("❌ Échec mise à jour statut")
            mysql.connection.rollback()
            return None
            
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"❌ Erreur create_or_update_booking: {str(e)}", exc_info=True)
        return None
    finally:
        cursor.close()

def cancel_booking(user_id, product_id, external_booking_id):
    """Annule une réservation et remet le statut à jour."""
    logger.info(f"Annulation réservation - user_id: {user_id}, booking_id: {external_booking_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        mysql.connection.begin()
        
        # Marquer la réservation comme annulée
        cursor.execute('''
            UPDATE bookings
            SET status = 'cancelled', updated_at = NOW()
            WHERE booking_id = %s AND user_id = %s
        ''', (external_booking_id, user_id))
        
        # Remettre le statut du produit à "achat_confirmé"
        update_user_product_status(
            user_id=user_id,
            product_id=product_id,
            status="achat_confirmé",
            booking_id=None,
            livrable_date=None,
            admin_note=f"RDV annulé - ID: {external_booking_id}"
        )
        
        mysql.connection.commit()
        logger.info(f"✅ Réservation annulée: {external_booking_id}")
        return True
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"❌ Erreur annulation: {str(e)}", exc_info=True)
        return False
    finally:
        cursor.close()

def reschedule_booking(user_id, product_id, external_booking_id, new_start_datetime, new_end_datetime=None):
    """Reprogramme une réservation avec nouvelles dates."""
    logger.info(f"Reprogrammation - user_id: {user_id}, booking_id: {external_booking_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        mysql.connection.begin()
        
        # Calculer la nouvelle durée
        duration = 60
        if new_end_datetime and new_start_datetime:
            duration = int((new_end_datetime - new_start_datetime).total_seconds() / 60)
        
        # Mettre à jour les dates
        cursor.execute('''
            UPDATE bookings 
            SET booking_date = %s, end_date = %s, duration_minutes = %s, updated_at = NOW()
            WHERE booking_id = %s AND user_id = %s
        ''', (new_start_datetime, new_end_datetime, duration, external_booking_id, user_id))
        
        # Recalculer la date de livraison
        livrable_date = add_business_days(new_start_datetime, 3)
        
        # Mettre à jour le statut avec la nouvelle date
        cursor.execute('''
            UPDATE product_status
            SET livrable_date = %s, updated_at = NOW()
            WHERE user_id = %s AND product_id = %s
        ''', (livrable_date, user_id, product_id))
        
        mysql.connection.commit()
        logger.info(f"✅ Réservation reprogrammée: {external_booking_id}")
        return True
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"❌ Erreur reprogrammation: {str(e)}", exc_info=True)
        return False
    finally:
        cursor.close()

# === FONCTIONS PRIVÉES === #

def _ensure_status_tables_exist():
    """S'assure que les tables de statut existent."""
    # Table product_status
    ensure_table_exists('product_status', '''
        CREATE TABLE IF NOT EXISTS product_status (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            product_id VARCHAR(50) NOT NULL,
            status VARCHAR(50) NOT NULL,
            booking_id INT NULL,
            livrable_date DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY unique_user_product (user_id, product_id),
            INDEX idx_status (status),
            INDEX idx_updated (updated_at)
        )
    ''')
    
    # Table product_status_updates
    ensure_table_exists('product_status_updates', '''
        CREATE TABLE IF NOT EXISTS product_status_updates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL,
            user_id INT NOT NULL,
            product_id VARCHAR(50) NOT NULL,
            old_status VARCHAR(50),
            new_status VARCHAR(50) NOT NULL,
            booking_id INT NULL,
            admin_id INT,
            admin_note TEXT,
            update_type VARCHAR(20) DEFAULT 'auto',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_order (order_id),
            INDEX idx_user_product (user_id, product_id),
            INDEX idx_created (created_at)
        )
    ''')

def _ensure_bookings_table_exists():
    """S'assure que la table bookings existe."""
    ensure_table_exists('bookings', '''
        CREATE TABLE IF NOT EXISTS bookings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            booking_id VARCHAR(100) NOT NULL UNIQUE,
            user_id INT NOT NULL,
            product_id VARCHAR(100) NOT NULL,
            booking_date DATETIME NOT NULL,
            end_date DATETIME,
            duration_minutes INT DEFAULT 60,
            attendee_email VARCHAR(255),
            attendee_name VARCHAR(255),
            booking_answers JSON,
            status VARCHAR(50) DEFAULT 'confirmed',
            zoom_link TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_user_product (user_id, product_id),
            INDEX idx_booking_id (booking_id),
            INDEX idx_booking_date (booking_date),
            INDEX idx_status (status)
        )
    ''')

def _trigger_status_notifications(user_id, product_id, status, booking_id):
    """Déclenche les notifications selon le statut."""
    try:
        if status == 'rdv_planifié' and booking_id:
            # Récupérer la date de RDV
            mysql = current_app.mysql
            cursor = mysql.connection.cursor(DictCursor)
            try:
                cursor.execute('SELECT booking_date FROM bookings WHERE id = %s', (booking_id,))
                result = cursor.fetchone()
                if result:
                    send_rdv_confirmation_email(user_id, result['booking_date'], product_id)
            finally:
                cursor.close()
                
        elif status == 'livrable_dispo':
            send_livrable_notification_email(user_id, product_id)
            
    except Exception as e:
        logger.error(f"Erreur notifications: {str(e)}")
        # Ne pas bloquer le processus principal
# === WEBHOOK YOUCANBOOK.ME OPTIMISÉ === #

@dashboard_bp.route('/product/<product_id>')
@login_required
def product_dashboard(product_id):
    """Dashboard produit avec vérification automatique RDV terminés."""
    logger.info(f"📦 Product dashboard - User: {current_user.id}, Product: {product_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # ✅ ÉTAPE 1: Vérification des RDV terminés AVANT tout traitement
        cursor.execute('''
            UPDATE product_status ps
            JOIN bookings b ON ps.booking_id = b.id
            SET ps.status = 'analyse_en_cours', 
                ps.updated_at = NOW(),
                ps.livrable_date = DATE_ADD(b.booking_date, INTERVAL 3 DAY)
            WHERE ps.user_id = %s 
              AND ps.product_id = %s
              AND ps.status = 'rdv_planifié'
              AND b.booking_date < NOW()
              AND TIMESTAMPDIFF(MINUTE, b.booking_date, NOW()) >= 30
        ''', (current_user.id, product_id))
        
        # Vérifier si une mise à jour a eu lieu
        if cursor.rowcount > 0:
            mysql.connection.commit()
            logger.info(f"✅ Statut mis à jour automatiquement : rdv_planifié → analyse_en_cours")
        
        # ✅ ÉTAPE 2: Continuer avec le code existant de votre fonction
        cursor.execute('''
            SELECT 
                pc.product_id, 
                pc.product_name, 
                pc.subtitle as description, 
                pc.product_type, 
                pc.unit_amount as price, 
                pc.emoji, 
                pc.image_url,
                o.order_id,
                o.order_number,
                o.created_at as purchase_date
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            JOIN product_catalog pc ON op.product_id = pc.product_id
            WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
            ORDER BY o.created_at DESC
            LIMIT 1
        ''', (current_user.id, product_id))
        
        product = cursor.fetchone()
        
        if not product:
            flash("Vous n'avez pas accès à ce produit.", "danger")
            return redirect(url_for('dashboard.index'))
        
        # Récupération du statut (fonction déjà corrigée)
        product_status = get_user_product_status(current_user.id, product_id)
        
        # Initialisation du statut si nécessaire
        if not product_status:
            update_user_product_status(
                user_id=current_user.id, 
                product_id=product_id, 
                status="achat_confirmé",
                order_id=product['order_id']
            )
            product_status = get_user_product_status(current_user.id, product_id)
        
        # ✅ CORRECTION: Logique d'image améliorée
        def get_product_display_image(product_data):
            """Version améliorée pour le dashboard produit"""
            image_url = product_data.get('image_url', '').strip()
            emoji = product_data.get('emoji', '').strip()
            
            if image_url and ('http' in image_url or image_url.startswith('/')):
                return f'<div class="product-image"><img src="{image_url}" alt="{product_data.get("product_name", "Produit")}" style="width: 100px; height: 100px; object-fit: cover; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);"></div>'
            elif emoji:
                return f'<div class="product-emoji" style="font-size: 4rem; text-align: center;">{emoji}</div>'
            else:
                return '<div class="product-emoji" style="font-size: 4rem; text-align: center;">📦</div>'
        
        # Informations enrichies du produit
        product_enriched = {
            'id': product['product_id'],
            'name': product['product_name'],
            'description': product['description'],
            'type': product['product_type'],
            'price': f"{(product['price'] / 100):.2f}" if product['price'] else "0.00",
            'image': get_product_display_image(product),  # ✅ CORRECTION
            'purchase_date': product['purchase_date'],
            'order_id': product['order_id'],
            'order_number': product['order_number']
        }
        
        # Informations de réservation
        booking_info = None
        if product_status and product_status.get('status') in ['rdv_planifié', 'analyse_en_cours', 'livrable_dispo', 'post_livraison']:
            booking_info = _get_booking_details(current_user.id, product_id)
        
        # Configuration de l'interface
        ui_config = {
            'can_book': product_status.get('status') == 'achat_confirmé' if product_status else True,
            'show_booking_widget': product_status.get('status') == 'achat_confirmé' if product_status else True,
            'show_booking_details': booking_info is not None,
            'can_download': product_status.get('status') in ['livrable_dispo', 'post_livraison'] if product_status else False,
            'can_give_feedback': product_status.get('status') == 'livrable_dispo' if product_status else False,
            'process_completed': product_status.get('status') == 'post_livraison' if product_status else False
        }
        
        # Statut avec informations visuelles
        current_status = product_status.get('status') if product_status else 'achat_confirmé'
        status_info = ORDER_STATUSES.get(current_status, ORDER_STATUSES['achat_confirmé'])
        
        # Timeline du processus
        timeline = _build_product_timeline(product_status or {'status': 'achat_confirmé'}, booking_info)
        
        logger.info(f"📋 Product loaded - Status: {current_status}, UI Config: {ui_config}")
        
        return render_template('pages/dashboard/product.html', 
                              product=product_enriched,
                              status=current_status,
                              status_info=status_info,
                              product_status=product_status,
                              booking_info=booking_info,
                              ui_config=ui_config,
                              timeline=timeline,
                              user=_get_user_info_cached(current_user.id),
                              now=datetime.now(),
                              timedelta=timedelta)
                              
    except Exception as e:
        logger.error(f"❌ Erreur product dashboard: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du chargement du produit.", "danger")
        return redirect(url_for('dashboard.index'))
    finally:
        cursor.close()

def _handle_booking_created(user_id, product_id, booking_id, webhook_data):
    """Traite la création d'une réservation."""
    logger.info(f"📅 Traitement création réservation - User: {user_id}, Product: {product_id}")
    
    try:
        # Extraire les dates depuis les données
        start_time = (webhook_data.get('startsAt') or 
                     webhook_data.get('startTime') or 
                     webhook_data.get('start_time'))
        
        end_time = (webhook_data.get('endsAt') or 
                   webhook_data.get('endTime') or 
                   webhook_data.get('end_time'))
        
        # Si pas de date, créer une date factice pour test
        if not start_time:
            # Date factice dans 1 semaine à 14h pour test
            from datetime import datetime, timedelta
            start_datetime = datetime.now() + timedelta(days=7)
            start_datetime = start_datetime.replace(hour=14, minute=0, second=0, microsecond=0)
            logger.warning(f"Pas de date dans webhook, utilisation date factice: {start_datetime}")
        else:
            try:
                start_datetime = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except:
                # Fallback: essayer d'autres formats
                start_datetime = datetime.now() + timedelta(days=7)
                start_datetime = start_datetime.replace(hour=14, minute=0, second=0, microsecond=0)
        
        # Date de fin
        end_datetime = None
        if end_time:
            try:
                end_datetime = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            except:
                end_datetime = start_datetime + timedelta(hours=1)
        else:
            end_datetime = start_datetime + timedelta(hours=1)
        
        # Informations participant
        attendee_email = (webhook_data.get('email') or 
                         webhook_data.get('attendeeEmail') or 
                         f"user_{user_id}@booking.temp")
        
        attendee_name = (webhook_data.get('name') or 
                        webhook_data.get('attendeeName') or 
                        f"Utilisateur {user_id}")
        
        zoom_link = webhook_data.get('zoomLink') or webhook_data.get('meetingUrl')
        
        # Créer la réservation dans la base
        booking_db_id = create_or_update_booking(
            user_id=user_id,
            product_id=product_id,
            external_booking_id=booking_id,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            attendee_email=attendee_email,
            attendee_name=attendee_name,
            answers=webhook_data,
            zoom_link=zoom_link
        )
        
        if booking_db_id:
            logger.info(f"✅ Réservation créée avec succès - ID: {booking_db_id}")
            return {
                'success': True,
                'action': 'created',
                'internal_booking_id': booking_db_id,
                'booking_date': start_datetime.isoformat(),
                'status': 'rdv_planifié'
            }
        else:
            logger.error("❌ Échec création réservation")
            return {'success': False, 'error': 'Échec création réservation'}
            
    except Exception as e:
        logger.error(f"❌ Erreur _handle_booking_created: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}

def _handle_booking_cancelled(user_id, product_id, booking_id, webhook_data):
    """Gère l'annulation d'une réservation."""
    logger.info(f"❌ Annulation réservation - ID: {booking_id}")
    
    try:
        success = cancel_booking(user_id, product_id, booking_id)
        
        if success:
            return {
                'success': True,
                'action': 'cancelled',
                'status': 'achat_confirmé'
            }
        else:
            return {'success': False, 'error': 'Échec annulation réservation'}
            
    except Exception as e:
        logger.error(f"Erreur annulation réservation: {str(e)}")
        return {'success': False, 'error': str(e)}

def _handle_booking_rescheduled(user_id, product_id, booking_id, webhook_data):
    """Gère la reprogrammation d'une réservation."""
    logger.info(f"🔄 Reprogrammation réservation - ID: {booking_id}")
    
    try:
        # Extraction des nouvelles dates
        new_start_time = webhook_data.get('startsAt') or webhook_data.get('startTime')
        new_end_time = webhook_data.get('endsAt') or webhook_data.get('endTime')
        
        if not new_start_time:
            return {'success': False, 'error': 'Nouvelle date de début manquante'}
        
        # Conversion des dates
        new_start_datetime = datetime.fromisoformat(new_start_time.replace('Z', '+00:00'))
        new_end_datetime = None
        if new_end_time:
            new_end_datetime = datetime.fromisoformat(new_end_time.replace('Z', '+00:00'))
        
        # Reprogrammation
        success = reschedule_booking(user_id, product_id, booking_id, new_start_datetime, new_end_datetime)
        
        if success:
            return {
                'success': True,
                'action': 'rescheduled',
                'new_booking_date': new_start_datetime.isoformat(),
                'status': 'rdv_planifié'
            }
        else:
            return {'success': False, 'error': 'Échec reprogrammation réservation'}
            
    except Exception as e:
        logger.error(f"Erreur reprogrammation réservation: {str(e)}")
        return {'success': False, 'error': str(e)}

# === PAGE DE SUCCÈS INTÉGRÉE AU FLOW === #

@dashboard_bp.route('/product/<product_id>/booking-success')
def booking_success(product_id):
    """
    Page de succès moderne avec mise à jour automatique du statut.
    """
    logger.info(f"📋 Booking Success - Product: {product_id}")
    
    # Correction automatique du product_id si vide
    if not product_id or product_id.strip() == '':
        product_id = 'pack_clarte_fr'
    
    # Récupération intelligente de l'user_id
    user_id = _get_user_id_from_context()
    
    if not user_id:
        return _render_booking_error("Utilisateur non identifié", product_id, {
            'url': request.url,
            'referrer': request.referrer,
            'args': dict(request.args)
        })
    
    # Validation de l'accès
    if not validate_user_product_access(user_id, product_id):
        return _render_booking_error("Accès non autorisé", product_id, {
            'user_id': user_id,
            'message': 'Produit non acheté par cet utilisateur'
        })
    
    # ✅ NOUVELLE PARTIE : Créer automatiquement le booking
    try:
        logger.info(f"🔨 Création automatique du booking pour user {user_id}, product {product_id}")
        
        # Générer un booking_id unique
        booking_id = f"success-{user_id}-{int(time.time())}"
        
        # Date de RDV dans 1 semaine à 14h (pour test)
        from datetime import datetime, timedelta
        booking_datetime = datetime.now() + timedelta(days=7)
        booking_datetime = booking_datetime.replace(hour=14, minute=0, second=0, microsecond=0)
        
        # Créer le booking
        booking_db_id = create_or_update_booking(
            user_id=user_id,
            product_id=product_id,
            external_booking_id=booking_id,
            start_datetime=booking_datetime,
            end_datetime=booking_datetime + timedelta(hours=1),
            attendee_email=f"user_{user_id}@booking.temp",
            attendee_name=f"Utilisateur {user_id}",
            answers={'source': 'booking_success_page', 'auto_created': True}
        )
        
        if booking_db_id:
            logger.info(f"✅ Booking créé automatiquement - ID: {booking_db_id}")
            booking_info = {
                'booking_id': booking_id,
                'booking_date': booking_datetime,
                'duration_minutes': 60
            }
        else:
            logger.warning("❌ Échec création booking automatique")
            booking_info = None
            
    except Exception as e:
        logger.error(f"❌ Erreur création booking automatique: {str(e)}")
        booking_info = None
    
    # Rendu de la page de succès
    return _render_booking_success(user_id, product_id, booking_info)

@dashboard_bp.route('/test-booking/<product_id>')
@login_required  
def test_booking_creation(product_id):
    """Route de test pour créer un booking manuellement."""
    logger.info(f"🧪 Test création booking - User: {current_user.id}, Product: {product_id}")
    
    try:
        # Générer un booking_id unique
        booking_id = f"test-{current_user.id}-{int(time.time())}"
        
        # Date dans 1 semaine
        from datetime import datetime, timedelta
        booking_datetime = datetime.now() + timedelta(days=7)
        booking_datetime = booking_datetime.replace(hour=15, minute=0, second=0, microsecond=0)
        
        # Créer le booking
        booking_db_id = create_or_update_booking(
            user_id=current_user.id,
            product_id=product_id,
            external_booking_id=booking_id,
            start_datetime=booking_datetime,
            end_datetime=booking_datetime + timedelta(hours=1),
            attendee_email=current_user.email,
            attendee_name=current_user.username,
            answers={'source': 'test_route'}
        )
        
        if booking_db_id:
            flash(f"✅ Test booking créé - ID: {booking_db_id}", "success")
        else:
            flash("❌ Échec création test booking", "danger")
            
    except Exception as e:
        logger.error(f"❌ Erreur test booking: {str(e)}")
        flash(f"❌ Erreur: {str(e)}", "danger")
    
    return redirect(url_for('dashboard.product_dashboard_by_status', status_id=2))


# ✅ AJOUTEZ cette route pour forcer la mise à jour du statut

@dashboard_bp.route('/force-status-update/<int:status_id>')
@login_required
def force_status_update(status_id):
    """Force la mise à jour du statut d'un produit."""
    logger.info(f"🔧 Force status update - User: {current_user.id}, Status ID: {status_id}")
    
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer les infos du produit
        cursor.execute('''
            SELECT ps.user_id, ps.product_id, ps.order_id, ps.status
            FROM product_status ps
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        product_status = cursor.fetchone()
        cursor.close()
        
        if not product_status:
            flash("❌ Produit non trouvé", "danger")
            return redirect(url_for('dashboard.index'))
        
        # Forcer la mise à jour vers rdv_planifié
        success = update_user_product_status(
            user_id=current_user.id,
            product_id=product_status['product_id'],
            status="rdv_planifié",
            admin_note="Mise à jour forcée par l'utilisateur",
            order_id=product_status['order_id']
        )
        
        if success:
            flash("✅ Statut mis à jour vers 'RDV planifié'", "success")
        else:
            flash("❌ Échec mise à jour statut", "danger")
            
    except Exception as e:
        logger.error(f"❌ Erreur force update: {str(e)}")
        flash(f"❌ Erreur: {str(e)}", "danger")
    
    return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))

def _get_user_id_from_context():
    """Récupère l'user_id depuis toutes les sources possibles."""
    # Ordre de priorité
    sources = [
        lambda: request.args.get('user_id'),
        lambda: current_user.id if current_user.is_authenticated else None,
        lambda: request.headers.get('X-User-ID'),
        lambda: request.form.get('user_id') if request.method == 'POST' else None,
        lambda: request.json.get('user_id') if request.json else None
    ]
    
    for source in sources:
        try:
            user_id = source()
            if user_id:
                return int(user_id)
        except (ValueError, TypeError, AttributeError):
            continue
    
    return None

def _get_latest_booking_info(user_id, product_id):
    """Récupère les informations de la dernière réservation."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT booking_id, booking_date, end_date, duration_minutes, 
                   attendee_name, zoom_link, status, created_at
            FROM bookings 
            WHERE user_id = %s AND product_id = %s
            ORDER BY created_at DESC 
            LIMIT 1
        ''', (user_id, product_id))
        
        return cursor.fetchone()
    except Exception as e:
        logger.error(f"Erreur récupération booking info: {str(e)}")
        return None
    finally:
        cursor.close()

def _render_booking_success(user_id, product_id, booking_info):
    """Rendu moderne de la page de succès avec design Tilto."""
    nonce = getattr(g, 'nonce', '')
    nonce_attr = f'nonce="{nonce}"' if nonce else ''
    
    # Information de base
    booking_date_str = ""
    if booking_info and booking_info.get('booking_date'):
        booking_date_str = format_date_fr(booking_info['booking_date'])
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Réservation confirmée - Tilto</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
                color: #2d3748;
            }}
            
            .success-container {{
                background: rgba(255, 255, 255, 0.95);
                backdrop-filter: blur(20px);
                border-radius: 24px;
                padding: 48px 40px;
                max-width: 500px;
                width: 100%;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
            }}
            
            .success-icon {{
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, #48bb78, #38a169);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 24px;
                animation: successBounce 0.6s ease-out;
            }}
            
            .success-icon::after {{
                content: "✓";
                color: white;
                font-size: 36px;
                font-weight: bold;
            }}
            
            .title {{
                font-size: 28px;
                font-weight: 700;
                color: #2d3748;
                margin-bottom: 12px;
                line-height: 1.2;
            }}
            
            .subtitle {{
                font-size: 16px;
                color: #4a5568;
                margin-bottom: 32px;
                line-height: 1.5;
            }}
            
            .booking-details {{
                background: #f7fafc;
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 32px;
                text-align: left;
            }}
            
            .detail-item {{
                display: flex;
                align-items: center;
                margin-bottom: 12px;
            }}
            
            .detail-item:last-child {{ margin-bottom: 0; }}
            
            .detail-icon {{
                width: 20px;
                height: 20px;
                margin-right: 12px;
                opacity: 0.7;
            }}
            
            .detail-label {{
                font-weight: 500;
                color: #2d3748;
                margin-right: 8px;
            }}
            
            .detail-value {{
                color: #4a5568;
                flex: 1;
            }}
            
            .action-buttons {{
                display: flex;
                gap: 12px;
                margin-top: 32px;
            }}
            
            .btn {{
                flex: 1;
                padding: 14px 20px;
                border-radius: 12px;
                font-weight: 500;
                text-decoration: none;
                transition: all 0.2s ease;
                border: none;
                cursor: pointer;
                font-size: 14px;
            }}
            
            .btn-primary {{
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
            }}
            
            .btn-primary:hover {{
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
            }}
            
            .btn-secondary {{
                background: white;
                color: #4a5568;
                border: 2px solid #e2e8f0;
            }}
            
            .btn-secondary:hover {{
                background: #f7fafc;
                border-color: #cbd5e0;
            }}
            
            .Tilto-badge {{
                display: inline-flex;
                align-items: center;
                gap: 8px;
                background: rgba(102, 126, 234, 0.1);
                color: #667eea;
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 500;
                margin-top: 24px;
            }}
            
            @keyframes successBounce {{
                0% {{ transform: scale(0.3); opacity: 0; }}
                50% {{ transform: scale(1.05); }}
                70% {{ transform: scale(0.9); }}
                100% {{ transform: scale(1); opacity: 1; }}
            }}
            
            @media (max-width: 480px) {{
                .success-container {{ padding: 32px 24px; }}
                .title {{ font-size: 24px; }}
                .action-buttons {{ flex-direction: column; }}
            }}
        </style>
    </head>
    <body>
        <div class="success-container">
            <div class="success-icon"></div>
            
            <h1 class="title">Réservation confirmée !</h1>
            <p class="subtitle">
                Votre rendez-vous a été enregistré avec succès. 
                Vous recevrez un email de confirmation dans quelques minutes.
            </p>
            
            {f'''
            <div class="booking-details">
                <div class="detail-item">
                    <span class="detail-icon">📅</span>
                    <span class="detail-label">Date :</span>
                    <span class="detail-value">{booking_date_str}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-icon">🎯</span>
                    <span class="detail-label">Produit :</span>
                    <span class="detail-value">Pack Clarté</span>
                </div>
                <div class="detail-item">
                    <span class="detail-icon">⏱️</span>
                    <span class="detail-label">Durée :</span>
                    <span class="detail-value">{booking_info.get('duration_minutes', 60)} minutes</span>
                </div>
            </div>
            ''' if booking_info else ''}
            
            <div class="action-buttons">
                <a href="/dashboard/product/{product_id}" class="btn btn-primary">
                    📋 Accéder au dashboard
                </a>
                <a href="/dashboard" class="btn btn-secondary">
                    🏠 Mes produits
                </a>
            </div>
            
            <div class="Tilto-badge">
                <span>✨</span>
                <span>Propulsé par Tilto</span>
            </div>
        </div>
        
        <script {nonce_attr}>
            // Notification à la page parent si dans une iframe
            if (window.parent !== window) {{
                window.parent.postMessage({{
                    type: 'Tilto:booking:success',
                    product_id: '{product_id}',
                    user_id: {user_id},
                    timestamp: new Date().toISOString(),
                    booking_date: '{booking_date_str}'
                }}, '*');
                
                // Auto-fermeture après 5 secondes
                setTimeout(() => {{
                    window.parent.postMessage({{
                        type: 'Tilto:close_iframe'
                    }}, '*');
                }}, 5000);
            }}
            
            // Animation d'entrée
            document.addEventListener('DOMContentLoaded', function() {{
                document.body.style.opacity = '0';
                document.body.style.transform = 'translateY(20px)';
                
                setTimeout(() => {{
                    document.body.style.transition = 'all 0.4s ease';
                    document.body.style.opacity = '1';
                    document.body.style.transform = 'translateY(0)';
                }}, 100);
            }});
        </script>
    </body>
    </html>
    """

def _render_booking_error(error_message, product_id, debug_info):
    """Rendu d'une page d'erreur avec design Tilto."""
    nonce = getattr(g, 'nonce', '')
    nonce_attr = f'nonce="{nonce}"' if nonce else ''
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Erreur - Tilto</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Inter', sans-serif;
                background: linear-gradient(135deg, #fc8181, #f56565);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .error-container {{
                background: white;
                border-radius: 16px;
                padding: 40px;
                max-width: 500px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }}
            
            .error-icon {{
                font-size: 64px;
                margin-bottom: 24px;
            }}
            
            .error-title {{
                font-size: 24px;
                font-weight: 600;
                color: #2d3748;
                margin-bottom: 16px;
            }}
            
            .error-message {{
                color: #4a5568;
                margin-bottom: 32px;
                line-height: 1.6;
            }}
            
            .debug-info {{
                background: #f7fafc;
                border-radius: 8px;
                padding: 16px;
                margin: 24px 0;
                font-size: 12px;
                color: #4a5568;
                text-align: left;
            }}
            
            .btn {{
                display: inline-block;
                background: #667eea;
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 500;
                transition: background 0.2s;
            }}
            
            .btn:hover {{
                background: #5a6fd8;
            }}
        </style>
    </head>
    <body>
        <div class="error-container">
            <div class="error-icon">⚠️</div>
            <h1 class="error-title">Oops ! Une erreur s'est produite</h1>
            <p class="error-message">{error_message}</p>
            
            <div class="debug-info">
                <strong>Informations de débogage :</strong><br>
                {json.dumps(debug_info, indent=2, default=str).replace('{', '').replace('}', '').replace('"', '')}
            </div>
            
            <a href="/dashboard" class="btn">← Retour au dashboard</a>
        </div>
        
        <script {nonce_attr}>
            if (window.parent !== window) {{
                window.parent.postMessage({{
                    type: 'Tilto:booking:error',
                    error: '{error_message}',
                    product_id: '{product_id}'
                }}, '*');
            }}
        </script>
    </body>
    </html>
    """

# === ROUTES PRINCIPALES OPTIMISÉES === #

# === CORRECTIONS POUR L'AFFICHAGE DES IMAGES PRODUITS ===

# 1. CORRECTION dans la fonction get_user_product_status
def get_user_product_status(user_id, product_id):
    """
    Version corrigée : récupère le statut d'un produit pour un utilisateur.
    CORRECTION : Utilise image_url au lieu d'emoji uniquement
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Requête corrigée pour récupérer AUSSI image_url
        cursor.execute('''
            SELECT 
                ps.id, ps.status, ps.livrable_date, ps.created_at, ps.updated_at,
                ps.booking_id, ps.order_id,
                pc.product_name, pc.subtitle as description, 
                pc.emoji, pc.image_url,  -- ✅ CORRECTION: Récupérer les deux
                b.booking_id as external_booking_id, b.booking_date, b.zoom_link
            FROM product_status ps
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            LEFT JOIN bookings b ON ps.booking_id = b.id
            WHERE ps.user_id = %s AND ps.product_id = %s
            ORDER BY ps.updated_at DESC
            LIMIT 1
        ''', (user_id, product_id))
        
        result = cursor.fetchone()
        
        if result:
            # ✅ CORRECTION: Prioriser image_url, fallback sur emoji
            display_image = result['image_url'] or result['emoji'] or '📦'
            
            result_dict = dict(result)
            result_dict['image_url'] = display_image  # Uniformiser
            return result_dict
        
        # Si aucun statut n'existe, vérifier si l'utilisateur a acheté ce produit
        cursor.execute('''
            SELECT o.order_id, pc.product_name, pc.subtitle as description, 
                   pc.emoji, pc.image_url  -- ✅ Récupérer aussi image_url
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            JOIN product_catalog pc ON op.product_id = pc.product_id
            WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
            LIMIT 1
        ''', (user_id, product_id))
        
        order_result = cursor.fetchone()
        if order_result:
            # ✅ CORRECTION: Même logique de priorisation
            display_image = order_result['image_url'] or order_result['emoji'] or '📦'
            
            # L'utilisateur a acheté ce produit mais n'a pas encore de statut
            cursor.execute('''
                INSERT INTO product_status (user_id, order_id, product_id, status)
                VALUES (%s, %s, %s, 'achat_confirmé')
            ''', (user_id, order_result['order_id'], product_id))
            
            mysql.connection.commit()
            
            return {
                'id': cursor.lastrowid,
                'status': 'achat_confirmé',
                'livrable_date': None,
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'booking_id': None,
                'order_id': order_result['order_id'],
                'product_name': order_result['product_name'],
                'description': order_result['description'],
                'image_url': display_image,  # ✅ CORRECTION
                'external_booking_id': None,
                'booking_date': None,
                'zoom_link': None
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Erreur récupération statut produit: {str(e)}")
        return None
    finally:
        cursor.close()

@dashboard_bp.route('/')
@login_required
def index():
    request_id = generate_request_id()
    cursor = current_app.mysql.connection.cursor(DictCursor)

    try:
        user_id = current_user.id
        quiz_id = 'pack_clarte'

        cursor.execute("SELECT firstname FROM users WHERE user_id = %s", (user_id,))
        user_row = cursor.fetchone()
        firstname = user_row['firstname'] if user_row else 'Utilisateur'

        # Vérifier Bilan Carrière Express en premier
        bilan_status = get_bilan_express_status(user_id)
        if bilan_status['has_bilan']:
            cursor.execute("SELECT phone_number FROM users WHERE user_id = %s", (user_id,))
            user_phone = cursor.fetchone()
            if not user_phone['phone_number']:
                return render_template('pages/dashboard/dashboard.html',
                    dashboard_state='bilan_phone_needed',
                    firstname=firstname
                )
            else:
                return render_template('pages/dashboard/dashboard.html',
                    dashboard_state='bilan_waiting',
                    firstname=firstname
                )

        sc_status = get_smart_contact_status(user_id)
        if sc_status['has_smart_contact']:
            cursor.execute("SELECT phone_number FROM users WHERE user_id = %s", (user_id,))
            user_phone = cursor.fetchone()
            
            if not user_phone['phone_number']:
                session['dashboard_state'] = 'smart_contact_phone_needed'
                return render_template('pages/dashboard/dashboard.html',
                    dashboard_state='smart_contact_phone_needed',
                    firstname=firstname
                )
            else:
                sc_product_status = sc_status.get('order_status', 'achat_confirmé')
                if sc_product_status in ('livrable_dispo', 'post_livraison'):
                    session['dashboard_state'] = 'smart_contact_delivered'
                    return render_template('pages/dashboard/dashboard.html',
                        dashboard_state='smart_contact_delivered',
                        smart_contact_product_id=sc_status['product_id'],
                        firstname=firstname
                    )
                else:
                    session['dashboard_state'] = 'smart_contact_waiting'
                    return render_template('pages/dashboard/dashboard.html',
                        dashboard_state='smart_contact_waiting',
                        firstname=firstname
                    )

        cursor.execute("""
            SELECT ru.result_id, ru.result_step_id
            FROM result_user ru
            JOIN analysis_notification_emails ane ON (
                ane.result_id = ru.result_id 
                AND ane.step_id = ru.result_step_id 
                AND ane.user_id = ru.user_id
            )
            WHERE ru.user_id = %s AND ru.quiz_id = %s AND ru.is_active = TRUE
            LIMIT 1
        """, (user_id, quiz_id))
        
        notified_analysis = cursor.fetchone()
        
        if notified_analysis:
            return redirect(url_for('quiz_analysis.view_analysis', 
                                quiz_id=quiz_id, 
                                result_id=notified_analysis['result_id'], 
                                step_id=notified_analysis['result_step_id']))

        cursor.execute("""
            SELECT 1 FROM async_analysis_jobs
            WHERE user_id = %s AND quiz_id = %s
            LIMIT 1
        """, (user_id, quiz_id))
        
        has_job = cursor.fetchone()
        
        if has_job:
            session['dashboard_state'] = 'processing'
            return render_template('pages/dashboard/dashboard.html',
                dashboard_state='processing',
                processing_status='humanized_wait',
                firstname=firstname
            )

        cursor.execute("""
            SELECT 1 FROM tokens 
            WHERE user_id = %s AND quiz_id = %s AND token_type IN ('paid', 'free')
            LIMIT 1
        """, (user_id, quiz_id))
        
        has_access = cursor.fetchone()
        
        if has_access:
            session['dashboard_state'] = 'processing'
            return render_template('pages/dashboard/dashboard.html',
                dashboard_state='processing',
                processing_status='humanized_wait',
                firstname=firstname
            )

        session['dashboard_state'] = 'locked'
        return render_template('pages/dashboard/dashboard.html',
            dashboard_state='locked',
            firstname=firstname,
            smart_contact_product_id='pack_smart_contact_fr'
        )
        
    except Exception as e:
        logger.error(f"[{request_id}] Dashboard error: {e}", exc_info=True)
        session['dashboard_state'] = 'error'
        return render_template('pages/dashboard/dashboard.html',
            dashboard_state='error',
            firstname='Utilisateur'
        )
        
    finally:
        cursor.close()


@dashboard_bp.route('/product-status/<int:status_id>/booking-notification', methods=['POST'])
@login_required
def booking_notification_by_status(status_id):
    """
    Notification côté client d'une réservation (fallback si webhook ne fonctionne pas).
    """
    logger.info(f"🔔 Client booking notification - Status ID: {status_id}")
    
    try:
        # Récupérer le product_id depuis status_id
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        cursor.execute('''
            SELECT ps.product_id, ps.user_id
            FROM product_status ps
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            return jsonify({'error': 'Produit non trouvé'}), 404
        
        product_id = result['product_id']
        
        # Récupérer les données de réservation depuis le client
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données manquantes'}), 400
        
        booking_data = data.get('booking_data', {})
        
        # Créer un booking_id temporaire si manquant
        booking_id = (booking_data.get('id') or 
                     booking_data.get('booking_id') or 
                     f"client-{current_user.id}-{int(time.time())}")
        
        logger.info(f"Traitement client notification - User: {current_user.id}, Product: {product_id}")
        
        # Traiter comme une création de réservation
        result = _handle_booking_created(current_user.id, product_id, booking_id, booking_data)
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'message': 'Réservation confirmée',
                'booking_id': booking_id,
                'status': 'rdv_planifié'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Erreur inconnue')
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Erreur notification client: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

# === ROUTES DE SIMULATION POUR DÉVELOPPEMENT === #

@dashboard_bp.route('/product/<product_id>/simulate/<action>', methods=['POST'])
@login_required
def simulate_action(product_id, action):
    """
    Simulation d'actions pour le développement et les tests.
    Actions disponibles: confirm-exchange, deliver-result, cancel-booking
    """
    if not current_app.debug:
        flash("Fonctionnalité disponible uniquement en mode développement.", "warning")
        return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
    
    logger.info(f"🧪 Simulation - User: {current_user.id}, Product: {product_id}, Action: {action}")
    
    try:
        status = get_user_product_status(current_user.id, product_id)
        if not status:
            flash("Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        booking_id = status.get('booking_db_id')
        
        if action == 'confirm-exchange':
            if status.get('status') != 'rdv_planifié':
                flash("L'échange ne peut être confirmé que pour un RDV planifié.", "warning")
            else:
                update_user_product_status(
                    user_id=current_user.id,
                    product_id=product_id,
                    status="analyse_en_cours",
                    booking_id=booking_id,
                    livrable_date=status.get('livrable_date'),
                    admin_note="Échange confirmé (simulation)"
                )
                flash("✅ Échange confirmé ! L'analyse est en cours.", "success")
        
        elif action == 'deliver-result':
            if status.get('status') != 'analyse_en_cours':
                flash("Le résultat ne peut être livré que pour une analyse en cours.", "warning")
            else:
                update_user_product_status(
                    user_id=current_user.id,
                    product_id=product_id,
                    status="livrable_dispo",
                    booking_id=booking_id,
                    livrable_date=datetime.now(),
                    admin_note="Livrable généré (simulation)"
                )
                flash("🎉 Votre diagnostic est maintenant disponible !", "success")
        
        elif action == 'cancel-booking':
            if booking_id:
                success = cancel_booking(current_user.id, product_id, status.get('booking_id', 'sim-cancel'))
                if success:
                    flash("❌ Réservation annulée avec succès.", "info")
                else:
                    flash("Erreur lors de l'annulation.", "danger")
            else:
                flash("Aucune réservation à annuler.", "warning")
        
        else:
            flash(f"Action '{action}' non reconnue.", "warning")
            
    except Exception as e:
        logger.error(f"❌ Erreur simulation: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors de la simulation.", "danger")
    
    return redirect(url_for('dashboard.product_dashboard', product_id=product_id))

# === FONCTIONS UTILITAIRES POUR LES ROUTES === #

def _get_user_info_cached(user_id):
    """Récupère les informations utilisateur avec mise en cache."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT username as name, email, created_at 
            FROM users 
            WHERE user_id = %s
        ''', (user_id,))
        
        result = cursor.fetchone()
        if result:
            return {
                'name': result['name'],
                'email': result['email'],
                'joined_at': result['created_at'],
                'member_since': format_date_fr(result['created_at'])
            }
        return None
        
    except Exception as e:
        logger.error(f"Erreur récupération user info: {str(e)}")
        return None
    finally:
        cursor.close()

def _get_booking_details(user_id, product_id):
    """Récupère les détails complets d'une réservation."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                b.id, b.booking_id, b.booking_date, b.end_date, 
                b.duration_minutes, b.attendee_name, b.attendee_email,
                b.booking_answers, b.status, b.zoom_link, b.created_at,
                b.updated_at
            FROM bookings b
            WHERE b.user_id = %s AND b.product_id = %s 
              AND b.status IN ('confirmed', 'rescheduled')
            ORDER BY b.created_at DESC
            LIMIT 1
        ''', (user_id, product_id))
        
        booking = cursor.fetchone()
        if booking:
            # Enrichissement des données
            booking_enriched = dict(booking)
            booking_enriched['formatted_date'] = format_date_fr(booking['booking_date'])
            booking_enriched['formatted_duration'] = f"{booking['duration_minutes']} minutes"
            
            # Analyse des réponses au formulaire si disponibles
            if booking['booking_answers']:
                try:
                    answers = json.loads(booking['booking_answers']) if isinstance(booking['booking_answers'], str) else booking['booking_answers']
                    booking_enriched['form_answers'] = answers
                except:
                    booking_enriched['form_answers'] = {}
            
            return booking_enriched
        
        return None
        
    except Exception as e:
        logger.error(f"Erreur récupération booking details: {str(e)}")
        return None
    finally:
        cursor.close()

def _build_product_timeline(product_status, booking_info):
    """Construit la timeline du processus produit."""
    timeline = []
    current_status = product_status.get('status', 'achat_confirmé')
    
    # Étapes de la timeline
    steps = [
        {
            'key': 'achat_confirmé',
            'title': 'Commande confirmée',
            'description': 'Votre achat a été validé',
            'icon': '📦',
            'date': product_status.get('created_at')
        },
        {
            'key': 'rdv_planifié',
            'title': 'Rendez-vous planifié',
            'description': 'Votre consultation est programmée',
            'icon': '📅',
            'date': booking_info.get('booking_date') if booking_info else None
        },
        {
            'key': 'analyse_en_cours',
            'title': 'Analyse en cours',
            'description': 'Nous analysons vos informations',
            'icon': '🔍',
            'date': None
        },
        {
            'key': 'livrable_dispo',
            'title': 'Résultat disponible',
            'description': 'Votre diagnostic est prêt',
            'icon': '✅',
            'date': product_status.get('livrable_date')
        },
        {
            'key': 'post_livraison',
            'title': 'Processus terminé',
            'description': 'Merci pour votre confiance',
            'icon': '🎉',
            'date': None
        }
    ]
    
    # Déterminer l'état de chaque étape
    status_order = ['achat_confirmé', 'rdv_planifié', 'analyse_en_cours', 'livrable_dispo', 'post_livraison']
    current_index = status_order.index(current_status) if current_status in status_order else 0
    
    for i, step in enumerate(steps):
        step_state = 'completed' if i < current_index else ('current' if i == current_index else 'pending')
        
        timeline.append({
            **step,
            'state': step_state,
            'is_current': step_state == 'current',
            'is_completed': step_state == 'completed',
            'formatted_date': format_date_fr(step['date']) if step['date'] else None
        })
    
    return timeline

# === ROUTES UTILISATEUR AVANCÉES === #

@dashboard_bp.route('/product/<product_id>/feedback', methods=['POST'])
@login_required
def submit_feedback(product_id):
    """
    Soumission de feedback utilisateur avec validation et traitement optimisé.
    Support des ratings, commentaires et suggestions d'amélioration.
    """
    logger.info(f"💬 Feedback submission - User: {current_user.id}, Product: {product_id}")
    
    try:
        # Validation des données
        rating = request.form.get('rating', type=int)
        comment = request.form.get('comment', '').strip()
        suggestions = request.form.get('suggestions', '').strip()
        recommend = request.form.get('recommend') == 'on'
        
        if not rating or rating < 1 or rating > 5:
            flash("⚠️ Veuillez fournir une note entre 1 et 5 étoiles.", "warning")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Création de la table feedback si nécessaire
            ensure_table_exists('product_feedback', '''
                CREATE TABLE IF NOT EXISTS product_feedback (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    product_id VARCHAR(50) NOT NULL,
                    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
                    comment TEXT,
                    suggestions TEXT,
                    recommend BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_user_product (user_id, product_id),
                    INDEX idx_rating (rating),
                    INDEX idx_created (created_at)
                )
            ''')
            
            # Vérifier si un feedback existe déjà
            cursor.execute('''
                SELECT id FROM product_feedback 
                WHERE user_id = %s AND product_id = %s
            ''', (current_user.id, product_id))
            
            existing_feedback = cursor.fetchone()
            
            if existing_feedback:
                # Mise à jour
                cursor.execute('''
                    UPDATE product_feedback 
                    SET rating = %s, comment = %s, suggestions = %s, 
                        recommend = %s, updated_at = NOW()
                    WHERE id = %s
                ''', (rating, comment, suggestions, recommend, existing_feedback['id']))
                
                logger.info(f"Feedback mis à jour - ID: {existing_feedback['id']}")
            else:
                # Création
                cursor.execute('''
                    INSERT INTO product_feedback 
                    (user_id, product_id, rating, comment, suggestions, recommend)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (current_user.id, product_id, rating, comment, suggestions, recommend))
                
                logger.info(f"Nouveau feedback créé - Rating: {rating}")
            
            # Mise à jour du statut du produit
            status = get_user_product_status(current_user.id, product_id)
            booking_id = status.get('booking_db_id') if status else None
            
            update_user_product_status(
                user_id=current_user.id,
                product_id=product_id,
                status="post_livraison",
                booking_id=booking_id,
                livrable_date=status.get('livrable_date') if status else None,
                admin_note=f"Feedback soumis - Note: {rating}/5"
            )
            
            mysql.connection.commit()
            
            # Message de succès personnalisé
            if rating >= 4:
                flash("🌟 Merci pour votre excellent retour ! Nous sommes ravis que vous soyez satisfait.", "success")
            else:
                flash("💙 Merci pour votre retour. Nous prenons vos commentaires très au sérieux.", "info")
            
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur soumission feedback: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors de l'enregistrement de votre feedback.", "danger")
    
    return redirect(url_for('dashboard.product_dashboard', product_id=product_id))

@dashboard_bp.route('/product/<product_id>/download-pdf')
@login_required
def download_pdf(product_id):
    """
    Téléchargement sécurisé du livrable PDF avec logging et analytics.
    """
    logger.info(f"📥 PDF download - User: {current_user.id}, Product: {product_id}")
    
    try:
        # Vérification des droits
        product_status = get_user_product_status(current_user.id, product_id)
        if not product_status or product_status.get('status') not in ['livrable_dispo', 'post_livraison']:
            flash("Ce livrable n'est pas encore disponible.", "warning")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        # Chemins possibles pour le PDF
        possible_paths = [
            os.path.join(current_app.root_path, 'static', 'livrables', f'{product_id}_{current_user.id}.pdf'),
            os.path.join(current_app.root_path, 'static', 'livrables', f'user_{current_user.id}_{product_id}.pdf'),
            os.path.join(current_app.root_path, 'static', 'livrables', f'{product_id}.pdf'),
        ]
        
        pdf_path = None
        for path in possible_paths:
            if os.path.exists(path):
                pdf_path = path
                break
        
        if not pdf_path:
            logger.warning(f"PDF non trouvé pour user {current_user.id}, product {product_id}")
            flash("Le fichier PDF n'est pas encore disponible. Notre équipe y travaille !", "info")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        # Logging du téléchargement
        _log_download_event(current_user.id, product_id, 'pdf')
        
        # Nom de fichier personnalisé
        timestamp = datetime.now().strftime("%Y%m%d")
        product_name = product_status.get('product_name', 'Tilto').replace(' ', '_')
        filename = f'{product_name}_{timestamp}.pdf'
        
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement PDF: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du téléchargement.", "danger")
        return redirect(url_for('dashboard.product_dashboard', product_id=product_id))

@dashboard_bp.route('/product/<product_id>/share', methods=['POST'])
@login_required
def share_product(product_id):
    """
    Partage sécurisé du livrable avec génération de lien temporaire.
    """
    logger.info(f"🔗 Product sharing - User: {current_user.id}, Product: {product_id}")
    
    try:
        recipient_email = request.form.get('email', '').strip().lower()
        message = request.form.get('message', '').strip()
        expiry_days = int(request.form.get('expiry_days', 7))
        
        # Validation
        if not recipient_email or '@' not in recipient_email:
            flash("⚠️ Veuillez fournir une adresse email valide.", "warning")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        # Vérification des droits
        product_status = get_user_product_status(current_user.id, product_id)
        if not product_status or product_status.get('status') not in ['livrable_dispo', 'post_livraison']:
            flash("Ce livrable n'est pas encore disponible pour être partagé.", "warning")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        # Génération du token de partage
        share_token = generate_share_token(current_user.id, product_id)
        expiry_date = datetime.now() + timedelta(days=expiry_days)
        
        # Enregistrement du partage
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Table des partages
            ensure_table_exists('product_shares', '''
                CREATE TABLE IF NOT EXISTS product_shares (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    product_id VARCHAR(50) NOT NULL,
                    recipient_email VARCHAR(255) NOT NULL,
                    share_token VARCHAR(255) NOT NULL UNIQUE,
                    message TEXT,
                    expiry_date DATETIME NOT NULL,
                    view_count INT DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_token (share_token),
                    INDEX idx_user_product (user_id, product_id),
                    INDEX idx_expiry (expiry_date)
                )
            ''')
            
            cursor.execute('''
                INSERT INTO product_shares 
                (user_id, product_id, recipient_email, share_token, message, expiry_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (current_user.id, product_id, recipient_email, share_token, message, expiry_date))
            
            mysql.connection.commit()
            
            
            
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur partage: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du partage.", "danger")
    
    return redirect(url_for('dashboard.product_dashboard', product_id=product_id))

# === ROUTES D'ADMINISTRATION OPTIMISÉES === #

@dashboard_bp.route('/admin/orders')
@admin_required
def admin_orders():
    """Interface d'administration avec affichage correct des images."""
    logger.info(f"👑 Admin orders access - User: {current_user.id}")
    
    # Paramètres de filtrage
    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '').strip()
    date_filter = request.args.get('date_range', '30')
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Construction de la requête avec filtres
        where_conditions = ["1=1"]
        params = []
        
        if status_filter and status_filter in ORDER_STATUSES:
            where_conditions.append("ps.status = %s")
            params.append(status_filter)
        
        if search_query:
            where_conditions.append("(u.username LIKE %s OR u.email LIKE %s OR pc.product_name LIKE %s)")
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param, search_param])
        
        if date_filter.isdigit():
            days = int(date_filter)
            where_conditions.append("ps.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)")
            params.append(days)
        
        where_clause = " AND ".join(where_conditions)
        
        # ✅ CORRECTION: Récupérer aussi les images dans l'admin
        cursor.execute(f'''
            SELECT 
                ps.id as order_id,
                ps.user_id,
                u.username as name,
                u.email,
                pc.product_name,
                pc.emoji,
                pc.image_url,  -- ✅ CORRECTION
                ps.status,
                ps.livrable_date,
                ps.created_at,
                ps.updated_at,
                ps.product_id,
                b.booking_date as rdv_date,
                b.attendee_email,
                b.zoom_link,
                b.booking_id as external_booking_id,
                b.status as booking_status,
                TIMESTAMPDIFF(HOUR, ps.created_at, NOW()) as hours_since_creation,
                CASE 
                    WHEN b.attendee_email IS NOT NULL THEN 'confirmed_booking'
                    WHEN ps.status = 'rdv_planifié' AND b.id IS NULL THEN 'manual_booking'
                    ELSE 'no_booking'
                END as booking_type
            FROM product_status ps
            JOIN users u ON ps.user_id = u.user_id
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            LEFT JOIN bookings b ON ps.booking_id = b.id
            WHERE {where_clause}
            ORDER BY ps.updated_at DESC
            LIMIT 100
        ''', params)
        
        orders = cursor.fetchall()
        
        # ✅ CORRECTION: Fonction d'affichage d'image pour l'admin
        def get_admin_display_image(order_data):
            """Image pour l'interface admin"""
            image_url = order_data.get('image_url', '').strip()
            emoji = order_data.get('emoji', '').strip()
            
            if image_url and ('http' in image_url or image_url.startswith('/')):
                return f'<img src="{image_url}" alt="Produit" style="width: 40px; height: 40px; object-fit: cover; border-radius: 8px;">'
            elif emoji:
                return f'<span style="font-size: 1.5rem;">{emoji}</span>'
            else:
                return '<span style="font-size: 1.5rem;">📦</span>'
        
        # Enrichissement des données de commandes
        enriched_orders = []
        for order in orders:
            status_info = ORDER_STATUSES.get(order['status'], ORDER_STATUSES['achat_confirmé'])
            
            enriched_orders.append({
                'order_id': order['order_id'],
                'user_id': order['user_id'],
                'name': order['name'],
                'email': order['email'],
                'product_name': order['product_name'],
                'product_id': order['product_id'],
                'product_image': get_admin_display_image(order),  # ✅ CORRECTION
                'status': order['status'],
                'status_info': status_info,
                'livrable_date': order['livrable_date'],
                'created_at': order['created_at'],
                'updated_at': order['updated_at'],
                'rdv_date': order['rdv_date'],
                'attendee_email': order['attendee_email'],
                'zoom_link': order['zoom_link'],
                'booking_info': {
                    'type': order['booking_type'],
                    'has_email': bool(order['attendee_email']),
                    'has_zoom': bool(order['zoom_link']),
                    'external_id': order['external_booking_id'],
                    'booking_status': order['booking_status']
                },
                'hours_since_creation': order['hours_since_creation'],
                'needs_attention': order['hours_since_creation'] > 72 and order['status'] == 'achat_confirmé',
                'formatted_created': format_date_fr(order['created_at']),
                'formatted_updated': format_date_fr(order['updated_at']),
                'formatted_rdv': format_date_fr(order['rdv_date']) if order['rdv_date'] else None,
                'age_display': _format_age_display(order['hours_since_creation'])
            })
            
        # Récupération des produits pour les filtres
        cursor.execute('SELECT DISTINCT product_id, product_name FROM product_catalog ORDER BY product_name')
        products = cursor.fetchall()
        
        # Préparation des données de filtres
        filters_data = {
            'status': status_filter,
            'search': search_query,
            'date_range': date_filter,
            'available_statuses': ORDER_STATUSES,
            'available_products': products
        }
        
        logger.info(f"📊 Admin orders loaded - Total: {len(enriched_orders)}, Stats: {stats}")
        
        return render_template('admin/orders.html',
                              orders=enriched_orders,
                              products=products,
                              order_statuses=ORDER_STATUSES,
                              stats=stats,
                              filters=filters_data)
                              
    except Exception as e:
        logger.error(f"❌ Erreur admin orders: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du chargement des commandes.", "danger")
        
        # Stats par défaut en cas d'erreur
        default_stats = {
            'total_orders': 0,
            'pending_bookings': 0,
            'scheduled_appointments': 0,
            'ready_deliverables': 0,
            'completed_orders': 0,
            'total_bookings': 0,
            'upcoming_bookings': 0,
            'booking_completion_rate': 0,
            'detailed_by_status': {}
        }
        
        return render_template('admin/orders.html', 
                              orders=[], 
                              products=[], 
                              order_statuses=ORDER_STATUSES, 
                              stats=default_stats, 
                              filters={
                                  'status': status_filter,
                                  'search': search_query,
                                  'date_range': date_filter,
                                  'available_statuses': ORDER_STATUSES,
                                  'available_products': []
                              })
    finally:
        cursor.close()

@dashboard_bp.route('/admin/update-status', methods=['POST'])
@admin_required
def admin_update_status():
    """
    Mise à jour administrative de statut avec validation et logging complet.
    """
    logger.info(f"⚙️ Admin status update - User: {current_user.id}")
    
    try:
        # Extraction et validation des données
        order_id = request.form.get('order_id', type=int)
        user_id = request.form.get('user_id', type=int)
        product_id = request.form.get('product_id', '').strip()
        new_status = request.form.get('new_status', '').strip()
        admin_note = request.form.get('admin_note', '').strip()
        
        # Données optionnelles
        rdv_date_str = request.form.get('rdv_date', '').strip()
        livrable_date_str = request.form.get('livrable_date', '').strip()
        send_notification = request.form.get('send_notification') == 'on'
        
        # Validation des données obligatoires
        if not all([order_id, user_id, product_id, new_status]):
            flash("❌ Tous les champs obligatoires doivent être remplis.", "danger")
            return redirect(url_for('dashboard.admin_orders'))
        
        if new_status not in ORDER_STATUSES:
            flash(f"❌ Statut '{new_status}' non valide.", "danger")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Conversion des dates
        rdv_date = None
        livrable_date = None
        
        try:
            if rdv_date_str:
                rdv_date = datetime.strptime(rdv_date_str, '%Y-%m-%dT%H:%M')
            if livrable_date_str:
                livrable_date = datetime.strptime(livrable_date_str, '%Y-%m-%d')
        except ValueError as e:
            flash(f"❌ Format de date invalide: {str(e)}", "danger")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Gestion spéciale pour rdv_planifié
        booking_id = None
        if new_status == 'rdv_planifié' and rdv_date:
            booking_id = _create_admin_booking(user_id, product_id, rdv_date, current_user.id)
            if not booking_id:
                flash("❌ Erreur lors de la création du rendez-vous.", "danger")
                return redirect(url_for('dashboard.admin_orders'))
        
        # Mise à jour du statut
        result = update_user_product_status(
            user_id=user_id,
            product_id=product_id,
            status=new_status,
            booking_id=booking_id,
            livrable_date=livrable_date,
            admin_id=current_user.id,
            admin_note=admin_note or f"Mise à jour manuelle par {current_user.username}",
            update_type='manual'
        )
        
        if result:
            # Notification optionnelle à l'utilisateur
            if send_notification:
                _send_status_update_notification(user_id, product_id, new_status)
            
            flash(f'✅ Statut mis à jour vers "{ORDER_STATUSES[new_status]["label"]}" avec succès !', 'success')
            logger.info(f"Status updated - Order: {order_id}, New status: {new_status}, Admin: {current_user.id}")
        else:
            flash('❌ Erreur lors de la mise à jour du statut.', 'danger')
            
    except Exception as e:
        logger.error(f"❌ Erreur admin update: {str(e)}", exc_info=True)
        flash("❌ Une erreur inattendue est survenue.", "danger")
    
    return redirect(url_for('dashboard.admin_orders'))

@dashboard_bp.route('/admin/bookings')
@admin_required
def admin_bookings():
    """
    Interface d'administration des réservations YouCanBookMe.
    Vue calendaire et liste avec actions avancées.
    """
    logger.info(f"📅 Admin bookings access - User: {current_user.id}")
    
    # Paramètres de vue
    view_mode = request.args.get('view', 'list')  # list ou calendar
    date_range = request.args.get('range', 'week')  # week, month, all
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Construction de la requête selon la plage de dates
        date_condition = ""
        params = []
        
        if date_range == 'week':
            date_condition = "AND b.booking_date >= DATE_SUB(NOW(), INTERVAL 1 WEEK)"
        elif date_range == 'month':
            date_condition = "AND b.booking_date >= DATE_SUB(NOW(), INTERVAL 1 MONTH)"
        
        cursor.execute(f'''
            SELECT 
                b.id, b.booking_id, b.booking_date, b.end_date, 
                b.duration_minutes, b.attendee_name, b.attendee_email,
                b.status as booking_status, b.zoom_link, b.created_at,
                b.updated_at, b.booking_answers,
                u.username, u.email as user_email, u.user_id,
                pc.product_name, pc.emoji as product_emoji,
                ps.status as order_status,
                CASE 
                    WHEN b.booking_date < NOW() AND b.status = 'confirmed' THEN 'past'
                    WHEN b.booking_date > NOW() AND b.status = 'confirmed' THEN 'upcoming'
                    ELSE b.status
                END as computed_status
            FROM bookings b
            JOIN users u ON b.user_id = u.user_id
            JOIN product_catalog pc ON b.product_id = pc.product_id
            LEFT JOIN product_status ps ON b.user_id = ps.user_id AND b.product_id = ps.product_id
            WHERE 1=1 {date_condition}
            ORDER BY b.booking_date DESC
            LIMIT 200
        ''', params)
        
        bookings_raw = cursor.fetchall()
        
        # Enrichissement des données
        bookings = []
        for booking in bookings_raw:
            # Analyse des réponses au formulaire
            form_data = {}
            if booking['booking_answers']:
                try:
                    form_data = json.loads(booking['booking_answers']) if isinstance(booking['booking_answers'], str) else booking['booking_answers']
                except:
                    pass
            
            bookings.append({
                **booking,
                'formatted_date': format_date_fr(booking['booking_date']),
                'formatted_end': format_date_fr(booking['end_date']) if booking['end_date'] else None,
                'is_past': booking['computed_status'] == 'past',
                'is_upcoming': booking['computed_status'] == 'upcoming',
                'can_cancel': booking['booking_status'] == 'confirmed' and booking['computed_status'] == 'upcoming',
                'form_data': form_data,
                'duration_display': f"{booking['duration_minutes']} min" if booking['duration_minutes'] else "60 min"
            })
        
        # Statistiques
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'confirmed' AND booking_date > NOW() THEN 1 ELSE 0 END) as upcoming,
                SUM(CASE WHEN status = 'confirmed' AND booking_date < NOW() THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
            FROM bookings
            WHERE booking_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        ''')
        
        stats = cursor.fetchone() or {'total': 0, 'upcoming': 0, 'completed': 0, 'cancelled': 0}
        
        return render_template('admin/bookings.html',
                              bookings=bookings,
                              stats=stats,
                              view_mode=view_mode,
                              date_range=date_range)
                              
    except Exception as e:
        logger.error(f"❌ Erreur admin bookings: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du chargement des réservations.", "danger")
        return render_template('admin/bookings.html', bookings=[], stats={})
    finally:
        cursor.close()

@dashboard_bp.route('/admin/cancel-booking/<booking_id>', methods=['POST'])
@admin_required
def admin_cancel_booking(booking_id):
    """Annulation administrative d'une réservation avec notification."""
    logger.info(f"❌ Admin booking cancellation - Booking: {booking_id}, Admin: {current_user.id}")
    
    try:
        reason = request.form.get('reason', '').strip()
        notify_user = request.form.get('notify_user') == 'on'
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Récupérer les détails de la réservation
            cursor.execute('''
                SELECT b.id, b.user_id, b.product_id, b.attendee_email, 
                       b.booking_date, u.username, pc.product_name
                FROM bookings b
                JOIN users u ON b.user_id = u.user_id
                JOIN product_catalog pc ON b.product_id = pc.product_id
                WHERE b.booking_id = %s
            ''', (booking_id,))
            
            booking = cursor.fetchone()
            
            if not booking:
                flash("❌ Réservation non trouvée.", "danger")
                return redirect(url_for('dashboard.admin_bookings'))
            
            # Annulation de la réservation
            success = cancel_booking(booking['user_id'], booking['product_id'], booking_id)
            
            if success:
                # Log de l'action admin
                cursor.execute('''
                    INSERT INTO admin_actions 
                    (admin_id, action_type, target_type, target_id, details, created_at)
                    VALUES (%s, 'cancel_booking', 'booking', %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE id=id
                ''', (current_user.id, booking['id'], json.dumps({
                    'reason': reason,
                    'booking_id': booking_id,
                    'user_id': booking['user_id']
                })))
                
                # Notification utilisateur si demandée
                if notify_user:
                    _send_booking_cancellation_notification(
                        booking['user_id'], 
                        booking['product_id'], 
                        booking['booking_date'],
                        reason
                    )
                
                mysql.connection.commit()
                flash(f"✅ Réservation annulée avec succès pour {booking['username']}.", "success")
                
            else:
                flash("❌ Erreur lors de l'annulation de la réservation.", "danger")
                
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur annulation admin: {str(e)}", exc_info=True)
        flash("❌ Une erreur est survenue lors de l'annulation.", "danger")
    
    return redirect(url_for('dashboard.admin_bookings'))


# === FONCTIONS UTILITAIRES PRIVÉES === #

def _create_admin_booking(user_id, product_id, rdv_date, admin_id):
    """Crée une réservation depuis l'interface admin."""
    external_booking_id = f"admin-{admin_id}-{int(time.time())}"
    
    return create_or_update_booking(
        user_id=user_id,
        product_id=product_id,
        external_booking_id=external_booking_id,
        start_datetime=rdv_date,
        end_datetime=rdv_date + timedelta(hours=1),
        duration=60,
        attendee_name="Réservation admin",
        answers={'source': 'admin', 'created_by': admin_id}
    )

def _log_download_event(user_id, product_id, file_type):
    """Enregistre un événement de téléchargement pour analytics."""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        ensure_table_exists('download_logs', '''
            CREATE TABLE IF NOT EXISTS download_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                product_id VARCHAR(50) NOT NULL,
                file_type VARCHAR(20) NOT NULL,
                ip_address VARCHAR(45),
                user_agent TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_product (user_id, product_id),
                INDEX idx_created (created_at)
            )
        ''')
        
        cursor.execute('''
            INSERT INTO download_logs 
            (user_id, product_id, file_type, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, product_id, file_type, 
              request.remote_addr, request.user_agent.string))
        
        mysql.connection.commit()
        cursor.close()
        
    except Exception as e:
        logger.error(f"Erreur log téléchargement: {str(e)}")

def _format_age_display(hours):
    """Formate l'âge d'une commande pour affichage."""
    if hours < 1:
        return "< 1h"
    elif hours < 24:
        return f"{int(hours)}h"
    elif hours < 168:  # 7 jours
        days = int(hours / 24)
        return f"{days}j"
    else:
        weeks = int(hours / 168)
        return f"{weeks}sem"

def _generate_calendar_link(rdv_date, title):
    """Génère un lien calendrier Google pour l'événement."""
    from urllib.parse import quote
    
    start_time = rdv_date.strftime('%Y%m%dT%H%M%S')
    end_time = (rdv_date + timedelta(hours=1)).strftime('%Y%m%dT%H%M%S')
    
    # Préparation des textes à encoder (évite les backslashes dans f-string)
    calendar_title = quote(title)
    calendar_description = quote("Rendez-vous Tilto - Plus d'informations sur votre dashboard")
    
    return (f"https://calendar.google.com/calendar/render?action=TEMPLATE"
            f"&text={calendar_title}"
            f"&dates={start_time}/{end_time}"
            f"&details={calendar_description}")


# === ROUTES D'ADMINISTRATION AVANCÉES === #

@dashboard_bp.route('/admin/upload-livrable/<int:order_id>', methods=['POST'])
@admin_required
def upload_livrable(order_id):
    """
    Upload sécurisé de livrables par les administrateurs.
    Support multi-formats avec validation et optimisation.
    """
    logger.info(f"📤 Admin livrable upload - Order: {order_id}, Admin: {current_user.id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Récupération des informations de commande
        cursor.execute('''
            SELECT ps.user_id, ps.product_id, u.email, u.username, pc.product_name
            FROM product_status ps
            JOIN users u ON ps.user_id = u.user_id
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            WHERE ps.id = %s
        ''', (order_id,))
        
        order_info = cursor.fetchone()
        
        if not order_info:
            flash("❌ Commande non trouvée.", "danger")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Validation du fichier
        if 'livrable_file' not in request.files:
            flash("❌ Aucun fichier fourni.", "warning")
            return redirect(url_for('dashboard.admin_orders'))
        
        file = request.files['livrable_file']
        if not file or file.filename == '':
            flash("❌ Aucun fichier sélectionné.", "warning")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Validation de l'extension
        allowed_extensions = {'.pdf', '.docx', '.zip'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            flash(f"❌ Type de fichier non autorisé. Extensions acceptées: {', '.join(allowed_extensions)}", "warning")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Validation de la taille (max 50MB)
        max_size = 50 * 1024 * 1024  # 50MB
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > max_size:
            flash("❌ Fichier trop volumineux (max 50MB).", "warning")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Préparation du stockage
        upload_folder = os.path.join(current_app.root_path, 'static', 'livrables')
        os.makedirs(upload_folder, exist_ok=True)
        
        # Nom de fichier sécurisé
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_filename = f"{order_info['product_id']}_{order_info['user_id']}_{timestamp}{file_ext}"
        file_path = os.path.join(upload_folder, safe_filename)
        
        # Sauvegarde du fichier
        try:
            file.save(file_path)
            
            # Validation du fichier sauvegardé
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise Exception("Fichier non sauvegardé correctement")
                
        except Exception as e:
            logger.error(f"Erreur sauvegarde fichier: {str(e)}")
            flash("❌ Erreur lors de la sauvegarde du fichier.", "danger")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Mise à jour du statut et logging
        mysql.connection.begin()
        
        try:
            # Mise à jour du statut
            update_user_product_status(
                user_id=order_info['user_id'],
                product_id=order_info['product_id'],
                status="livrable_dispo",
                admin_id=current_user.id,
                admin_note=f"Livrable uploadé par {current_user.username} - Fichier: {file.filename}",
                update_type='manual'
            )
            
            # Log de l'upload
            ensure_table_exists('file_uploads', '''
                CREATE TABLE IF NOT EXISTS file_uploads (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    product_id VARCHAR(50) NOT NULL,
                    admin_id INT NOT NULL,
                    original_filename VARCHAR(255) NOT NULL,
                    stored_filename VARCHAR(255) NOT NULL,
                    file_size INT NOT NULL,
                    file_type VARCHAR(10) NOT NULL,
                    upload_path TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_product (user_id, product_id),
                    INDEX idx_admin (admin_id),
                    INDEX idx_created (created_at)
                )
            ''')
            
            cursor.execute('''
                INSERT INTO file_uploads 
                (user_id, product_id, admin_id, original_filename, stored_filename, 
                 file_size, file_type, upload_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (order_info['user_id'], order_info['product_id'], current_user.id,
                  file.filename, safe_filename, file_size, file_ext, file_path))
            
            mysql.connection.commit()
            
            # Notification utilisateur
            email_sent = send_livrable_notification_email(order_info['user_id'], order_info['product_id'])
            
            success_msg = f"✅ Livrable uploadé avec succès pour {order_info['username']}"
            if email_sent:
                success_msg += " et notification envoyée."
            else:
                success_msg += " mais erreur d'envoi de notification."
            
            flash(success_msg, "success")
            logger.info(f"Livrable uploadé - User: {order_info['user_id']}, Admin: {current_user.id}, File: {safe_filename}")
            
        except Exception as e:
            mysql.connection.rollback()
            # Suppression du fichier en cas d'erreur DB
            if os.path.exists(file_path):
                os.remove(file_path)
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur upload livrable: {str(e)}", exc_info=True)
        flash("❌ Une erreur est survenue lors de l'upload.", "danger")
    
    return redirect(url_for('dashboard.admin_orders'))

@dashboard_bp.route('/admin/analytics')
@admin_required
def admin_analytics():
    """
    Dashboard d'analytics avancé pour les administrateurs.
    Métriques de performance, conversion et satisfaction.
    """
    logger.info(f"📊 Admin analytics access - User: {current_user.id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Période d'analyse (30 derniers jours par défaut)
        days = request.args.get('days', 30, type=int)
        
        # Métriques principales
        cursor.execute('''
            SELECT 
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status = 'achat_confirmé' THEN 1 END) as pending_bookings,
                COUNT(CASE WHEN status = 'rdv_planifié' THEN 1 END) as scheduled_appointments,
                COUNT(CASE WHEN status = 'livrable_dispo' THEN 1 END) as ready_deliverables,
                COUNT(CASE WHEN status = 'post_livraison' THEN 1 END) as completed_orders,
                AVG(TIMESTAMPDIFF(HOUR, created_at, 
                    CASE WHEN status = 'post_livraison' THEN updated_at ELSE NULL END)) as avg_completion_hours
            FROM product_status 
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        ''', (days,))
        
        main_metrics = cursor.fetchone()
        
        # Évolution par jour
        cursor.execute('''
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as new_orders,
                COUNT(CASE WHEN status = 'post_livraison' THEN 1 END) as completed
            FROM product_status 
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY DATE(created_at)
            ORDER BY date
        ''', (days,))
        
        daily_evolution = cursor.fetchall()
        
        # Répartition par statut
        cursor.execute('''
            SELECT status, COUNT(*) as count
            FROM product_status 
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY status
        ''', (days,))
        
        status_distribution = cursor.fetchall()
        
        # Métriques de réservations
        cursor.execute('''
            SELECT 
                COUNT(*) as total_bookings,
                COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as confirmed,
                COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled,
                AVG(duration_minutes) as avg_duration,
                COUNT(CASE WHEN booking_date > NOW() THEN 1 END) as upcoming
            FROM bookings 
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        ''', (days,))
        
        booking_metrics = cursor.fetchone()
        
        # Satisfaction client (feedbacks)
        cursor.execute('''
            SELECT 
                AVG(rating) as avg_rating,
                COUNT(*) as total_feedbacks,
                COUNT(CASE WHEN rating >= 4 THEN 1 END) as positive_feedbacks,
                COUNT(CASE WHEN recommend = 1 THEN 1 END) as recommendations
            FROM product_feedback 
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        ''', (days,))
        
        satisfaction_metrics = cursor.fetchone()
        
        # Top produits
        cursor.execute('''
            SELECT 
                pc.product_name,
                pc.product_id,
                COUNT(ps.id) as order_count,
                AVG(pf.rating) as avg_rating
            FROM product_status ps
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            LEFT JOIN product_feedback pf ON ps.user_id = pf.user_id AND ps.product_id = pf.product_id
            WHERE ps.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY pc.product_id, pc.product_name
            ORDER BY order_count DESC
            LIMIT 10
        ''', (days,))
        
        top_products = cursor.fetchall()
        
        # Calculs de conversion
        conversion_rates = {}
        if main_metrics['total_orders'] > 0:
            conversion_rates = {
                'booking_rate': (main_metrics['scheduled_appointments'] / main_metrics['total_orders']) * 100,
                'completion_rate': (main_metrics['completed_orders'] / main_metrics['total_orders']) * 100,
                'satisfaction_rate': (satisfaction_metrics['positive_feedbacks'] / satisfaction_metrics['total_feedbacks'] * 100) if satisfaction_metrics['total_feedbacks'] > 0 else 0
            }
        
        # Préparation des données pour les graphiques
        analytics_data = {
            'main_metrics': main_metrics,
            'daily_evolution': daily_evolution,
            'status_distribution': status_distribution,
            'booking_metrics': booking_metrics,
            'satisfaction_metrics': satisfaction_metrics,
            'top_products': top_products,
            'conversion_rates': conversion_rates,
            'period_days': days
        }
        
        return render_template('admin/analytics.html', 
                              analytics=analytics_data,
                              order_statuses=ORDER_STATUSES)
                              
    except Exception as e:
        logger.error(f"❌ Erreur analytics: {str(e)}", exc_info=True)
        flash("❌ Erreur lors du chargement des analytics.", "danger")
        return render_template('admin/analytics.html', analytics={}, order_statuses=ORDER_STATUSES)
    finally:
        cursor.close()

@dashboard_bp.route('/admin/bulk-actions', methods=['POST'])
@admin_required
def admin_bulk_actions():
    """
    Actions en masse pour l'administration.
    Permet de traiter plusieurs commandes simultanément.
    """
    logger.info(f"🔄 Admin bulk actions - User: {current_user.id}")
    
    try:
        action = request.form.get('action', '').strip()
        selected_orders = request.form.getlist('selected_orders')
        
        if not action or not selected_orders:
            flash("❌ Action ou sélection manquante.", "warning")
            return redirect(url_for('dashboard.admin_orders'))
        
        # Validation des IDs de commandes
        try:
            order_ids = [int(order_id) for order_id in selected_orders]
        except ValueError:
            flash("❌ IDs de commandes invalides.", "danger")
            return redirect(url_for('dashboard.admin_orders'))
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            success_count = 0
            error_count = 0
            
            if action == 'bulk_status_update':
                new_status = request.form.get('bulk_new_status', '').strip()
                bulk_note = request.form.get('bulk_note', '').strip()
                
                if new_status not in ORDER_STATUSES:
                    flash("❌ Statut invalide pour mise à jour en masse.", "danger")
                    return redirect(url_for('dashboard.admin_orders'))
                
                # Récupération des informations des commandes
                placeholders = ','.join(['%s'] * len(order_ids))
                cursor.execute(f'''
                    SELECT ps.id, ps.user_id, ps.product_id 
                    FROM product_status ps 
                    WHERE ps.id IN ({placeholders})
                ''', order_ids)
                
                orders = cursor.fetchall()
                
                for order in orders:
                    try:
                        result = update_user_product_status(
                            user_id=order['user_id'],
                            product_id=order['product_id'],
                            status=new_status,
                            admin_id=current_user.id,
                            admin_note=bulk_note or f"Mise à jour en masse vers {new_status}",
                            update_type='bulk'
                        )
                        
                        if result:
                            success_count += 1
                        else:
                            error_count += 1
                            
                    except Exception as e:
                        logger.error(f"Erreur mise à jour commande {order['id']}: {str(e)}")
                        error_count += 1
            
            elif action == 'bulk_send_notifications':
                # Envoi de notifications en masse
                placeholders = ','.join(['%s'] * len(order_ids))
                cursor.execute(f'''
                    SELECT ps.user_id, ps.product_id, ps.status 
                    FROM product_status ps 
                    WHERE ps.id IN ({placeholders})
                ''', order_ids)
                
                orders = cursor.fetchall()
                
                for order in orders:
                    try:
                        if order['status'] == 'rdv_planifié':
                            # Récupération de la date de RDV
                            cursor.execute('''
                                SELECT b.booking_date 
                                FROM bookings b 
                                JOIN product_status ps ON b.id = ps.booking_id
                                WHERE ps.user_id = %s AND ps.product_id = %s
                            ''', (order['user_id'], order['product_id']))
                            
                            booking = cursor.fetchone()
                            if booking:
                                send_rdv_confirmation_email(order['user_id'], booking['booking_date'], order['product_id'])
                                success_count += 1
                        
                        elif order['status'] == 'livrable_dispo':
                            send_livrable_notification_email(order['user_id'], order['product_id'])
                            success_count += 1
                        else:
                            error_count += 1
                            
                    except Exception as e:
                        logger.error(f"Erreur notification commande {order['user_id']}: {str(e)}")
                        error_count += 1
            
            else:
                flash(f"❌ Action '{action}' non supportée.", "warning")
                return redirect(url_for('dashboard.admin_orders'))
            
            mysql.connection.commit()
            
            # Message de résultat
            if success_count > 0:
                flash(f"✅ {success_count} commande(s) traitée(s) avec succès.", "success")
            
            if error_count > 0:
                flash(f"⚠️ {error_count} erreur(s) lors du traitement.", "warning")
            
            logger.info(f"Bulk action '{action}' - Success: {success_count}, Errors: {error_count}")
            
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur actions en masse: {str(e)}", exc_info=True)
        flash("❌ Erreur lors des actions en masse.", "danger")
    
    return redirect(url_for('dashboard.admin_orders'))

# === ROUTES API POUR INTÉGRATIONS === #

@dashboard_bp.route('/api/status/<int:user_id>/<product_id>')
@login_required
def api_get_status(user_id, product_id):
    """
    API REST pour récupérer le statut d'un produit.
    Utilisé pour les intégrations externes et les SPAs.
    """
    # Vérification des droits (admin ou propriétaire)
    if not (current_user.is_admin or current_user.id == user_id):
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        status = get_user_product_status(user_id, product_id)
        
        if not status:
            return jsonify({'error': 'Produit non trouvé'}), 404
        
        # Formatage des données pour l'API
        api_response = {
            'user_id': user_id,
            'product_id': product_id,
            'status': status['status'],
            'status_info': ORDER_STATUSES.get(status['status'], {}),
            'booking_date': status['booking_date'].isoformat() if status.get('booking_date') else None,
            'livrable_date': status['livrable_date'].isoformat() if status.get('livrable_date') else None,
            'last_updated': status['updated_at'].isoformat() if status.get('updated_at') else None,
            'booking_info': {
                'booking_id': status.get('booking_id'),
                'zoom_link': status.get('zoom_link')
            } if status.get('booking_id') else None
        }
        
        return jsonify(api_response)
        
    except Exception as e:
        logger.error(f"❌ Erreur API status: {str(e)}")
        return jsonify({'error': 'Erreur interne'}), 500

@dashboard_bp.route('/api/webhook-test', methods=['POST'])
@csrf.exempt
def api_webhook_test():
    """
    Endpoint de test pour le webhook YouCanBookMe.
    Permet de valider la configuration sans traiter réellement.
    """
    if not current_app.debug:
        return jsonify({'error': 'Disponible uniquement en mode debug'}), 403
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON manquantes'}), 400
        
        # Simulation de l'extraction d'user_id
        user_id = extract_user_id_from_webhook(data)
        
        # Test de validation
        test_results = {
            'webhook_data_received': True,
            'user_id_extracted': user_id is not None,
            'user_id_value': user_id,
            'event_type': data.get('type', 'unknown'),
            'booking_id': data.get('id'),
            'has_start_time': bool(data.get('startsAt') or data.get('startTime')),
            'form_fields': len(data.get('formFields', [])),
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'message': 'Test webhook réussi',
            'test_results': test_results
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur test webhook: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# === INITIALISATION ET NETTOYAGE === #

@dashboard_bp.before_app_first_request
def init_dashboard():
    """Initialisation du module dashboard au premier démarrage."""
    logger.info("🚀 Initialisation du module Dashboard")
    
    try:
        # Création des tables d'administration si nécessaire
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Table des actions admin
        ensure_table_exists('admin_actions', '''
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                admin_id INT NOT NULL,
                action_type VARCHAR(50) NOT NULL,
                target_type VARCHAR(50) NOT NULL,
                target_id VARCHAR(100) NOT NULL,
                details JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_admin (admin_id),
                INDEX idx_action_type (action_type),
                INDEX idx_created (created_at)
            )
        ''')
        
        cursor.close()
        logger.info("✅ Tables d'administration initialisées")
        
    except Exception as e:
        logger.error(f"❌ Erreur initialisation dashboard: {str(e)}")

@dashboard_bp.teardown_app_request
def cleanup_dashboard(exception):
    """Nettoyage après chaque requête."""
    if exception:
        logger.error(f"Exception dans dashboard: {str(exception)}")

# === FILTRES ET HELPERS POUR TEMPLATES === #

@dashboard_bp.app_template_filter('time_ago')
def time_ago_filter(datetime_obj):
    """Affiche le temps écoulé de manière lisible."""
    if not datetime_obj:
        return ""
    
    now = datetime.now()
    diff = now - datetime_obj
    
    if diff.days > 0:
        return f"il y a {diff.days} jour{'s' if diff.days > 1 else ''}"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"il y a {hours} heure{'s' if hours > 1 else ''}"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"il y a {minutes} minute{'s' if minutes > 1 else ''}"
    else:
        return "à l'instant"

@dashboard_bp.app_template_filter('duration_format')
def duration_format_filter(minutes):
    """Formate une durée en minutes."""
    if not minutes:
        return "Non défini"
    
    if minutes < 60:
        return f"{minutes} min"
    else:
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes == 0:
            return f"{hours}h"
        else:
            return f"{hours}h{remaining_minutes:02d}"

@dashboard_bp.app_context_processor
def inject_dashboard_globals():
    """Injecte des variables globales dans tous les templates du dashboard."""
    return {
        'ORDER_STATUSES': ORDER_STATUSES,
        'current_time': datetime.now(),
        'dashboard_version': '2.0'
    }

@dashboard_bp.route('/product/<product_id>/booking/cancel', methods=['POST'])
@login_required
def cancel_user_booking(product_id):
    """
    Annulation d'un rendez-vous par l'utilisateur.
    Avec confirmation et possibilité de re-réserver.
    """
    logger.info(f"❌ User booking cancellation - User: {current_user.id}, Product: {product_id}")
    
    try:
        reason = request.form.get('reason', '').strip()
        
        # Récupération des informations de réservation
        product_status = get_user_product_status(current_user.id, product_id)
        if not product_status or product_status.get('status') != 'rdv_planifié':
            flash("❌ Aucun rendez-vous à annuler pour ce produit.", "warning")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        booking_info = _get_booking_details(current_user.id, product_id)
        if not booking_info:
            flash("❌ Informations de rendez-vous introuvables.", "danger")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        # Vérification du délai d'annulation (min 24h avant)
        booking_date = booking_info['booking_date']
        hours_until_booking = (booking_date - datetime.now()).total_seconds() / 3600
        
        if hours_until_booking < 24:
            flash("⚠️ Impossible d'annuler un rendez-vous moins de 24h avant. Contactez notre équipe.", "warning")
            return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Annulation de la réservation
            success = cancel_booking(current_user.id, product_id, booking_info['booking_id'])
            
            if success:
                # Log de l'annulation utilisateur
                cursor.execute('''
                    INSERT INTO user_booking_actions 
                    (user_id, product_id, booking_id, action_type, reason, created_at)
                    VALUES (%s, %s, %s, 'cancel', %s, NOW())
                    ON DUPLICATE KEY UPDATE id=id
                ''', (current_user.id, product_id, booking_info['booking_id'], reason))
                
                # Notification par email à l'équipe
                _notify_team_booking_cancellation(current_user.id, product_id, booking_date, reason)
                
                mysql.connection.commit()
                
                flash("✅ Votre rendez-vous a été annulé avec succès. Vous pouvez programmer un nouveau créneau.", "success")
                logger.info(f"User booking cancelled - User: {current_user.id}, Booking: {booking_info['booking_id']}")
                
            else:
                flash("❌ Erreur lors de l'annulation. Veuillez réessayer.", "danger")
                
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur annulation utilisateur: {str(e)}", exc_info=True)
        flash("❌ Une erreur est survenue lors de l'annulation.", "danger")
    
    return redirect(url_for('dashboard.product_dashboard', product_id=product_id))

@dashboard_bp.route('/product/<product_id>/booking/reschedule', methods=['GET', 'POST'])
@login_required
def reschedule_user_booking(product_id):
    """
    Reprogrammation d'un rendez-vous par l'utilisateur.
    Interface moderne avec calendrier intégré.
    """
    logger.info(f"🔄 User booking reschedule - User: {current_user.id}, Product: {product_id}")
    
    # Vérifications préliminaires
    product_status = get_user_product_status(current_user.id, product_id)
    if not product_status or product_status.get('status') != 'rdv_planifié':
        flash("❌ Aucun rendez-vous à reprogrammer pour ce produit.", "warning")
        return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
    
    booking_info = _get_booking_details(current_user.id, product_id)
    if not booking_info:
        flash("❌ Informations de rendez-vous introuvables.", "danger")
        return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
    
    # Vérification du délai de reprogrammation (min 48h avant)
    booking_date = booking_info['booking_date']
    hours_until_booking = (booking_date - datetime.now()).total_seconds() / 3600
    
    if hours_until_booking < 48:
        flash("⚠️ Impossible de reprogrammer un rendez-vous moins de 48h avant. Contactez notre équipe.", "warning")
        return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
    
    if request.method == 'GET':
        # Affichage de l'interface de reprogrammation
        return render_template('pages/dashboard/reschedule_booking.html',
                              product_id=product_id,
                              current_booking=booking_info,
                              product_status=product_status,
                              user=_get_user_info_cached(current_user.id))
    
    # POST - Traitement de la reprogrammation
    try:
        new_date_str = request.form.get('new_date', '').strip()
        new_time_str = request.form.get('new_time', '').strip()
        reason = request.form.get('reason', '').strip()
        
        if not new_date_str or not new_time_str:
            flash("❌ Veuillez sélectionner une nouvelle date et heure.", "warning")
            return redirect(url_for('dashboard.reschedule_user_booking', product_id=product_id))
        
        # Conversion de la nouvelle date/heure
        try:
            new_datetime_str = f"{new_date_str} {new_time_str}"
            new_datetime = datetime.strptime(new_datetime_str, '%Y-%m-%d %H:%M')
            
            # Vérification que la nouvelle date est dans le futur
            if new_datetime <= datetime.now():
                flash("❌ La nouvelle date doit être dans le futur.", "warning")
                return redirect(url_for('dashboard.reschedule_user_booking', product_id=product_id))
            
            # Vérification des heures ouvrables (9h-18h, lundi-vendredi)
            if new_datetime.weekday() > 4 or new_datetime.hour < 9 or new_datetime.hour >= 18:
                flash("⚠️ Veuillez choisir un créneau pendant les heures ouvrables (9h-18h, lundi-vendredi).", "warning")
                return redirect(url_for('dashboard.reschedule_user_booking', product_id=product_id))
                
        except ValueError:
            flash("❌ Format de date/heure invalide.", "danger")
            return redirect(url_for('dashboard.reschedule_user_booking', product_id=product_id))
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Reprogrammation
            success = reschedule_booking(
                current_user.id, 
                product_id, 
                booking_info['booking_id'], 
                new_datetime,
                new_datetime + timedelta(hours=1)
            )
            
            if success:
                # Log de la reprogrammation
                cursor.execute('''
                    INSERT INTO user_booking_actions 
                    (user_id, product_id, booking_id, action_type, reason, new_datetime, created_at)
                    VALUES (%s, %s, %s, 'reschedule', %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE id=id
                ''', (current_user.id, product_id, booking_info['booking_id'], reason, new_datetime))
                
                # Notifications
                _notify_team_booking_reschedule(current_user.id, product_id, booking_date, new_datetime, reason)
                send_rdv_confirmation_email(current_user.id, new_datetime, product_id)
                
                mysql.connection.commit()
                
                flash(f"✅ Votre rendez-vous a été reprogrammé au {format_date_fr(new_datetime)}.", "success")
                logger.info(f"User booking rescheduled - User: {current_user.id}, New date: {new_datetime}")
                
                return redirect(url_for('dashboard.product_dashboard', product_id=product_id))
                
            else:
                flash("❌ Erreur lors de la reprogrammation. Veuillez réessayer.", "danger")
                
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur reprogrammation utilisateur: {str(e)}", exc_info=True)
        flash("❌ Une erreur est survenue lors de la reprogrammation.", "danger")
    
    return redirect(url_for('dashboard.reschedule_user_booking', product_id=product_id))

@dashboard_bp.route('/product/<product_id>/booking/details')
@login_required  
def booking_details(product_id):
    """
    Affichage détaillé des informations de rendez-vous.
    Avec possibilité d'export calendrier et notes personnelles.
    """
    logger.info(f"📋 Booking details - User: {current_user.id}, Product: {product_id}")
    
    try:
        # Vérifications
        product_status = get_user_product_status(current_user.id, product_id)
        if not product_status:
            flash("❌ Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.index'))
        
        booking_info = _get_booking_details(current_user.id, product_id)
        
        # Informations enrichies
        enriched_info = None
        if booking_info:
            enriched_info = {
                **booking_info,
                'can_cancel': _can_cancel_booking(booking_info['booking_date']),
                'can_reschedule': _can_reschedule_booking(booking_info['booking_date']),
                'calendar_link': _generate_calendar_link(booking_info['booking_date'], 
                                                       product_status.get('product_name', 'Rendez-vous Tilto')),
                'time_until_booking': _format_time_until(booking_info['booking_date']),
                'preparation_checklist': _get_preparation_checklist(product_id)
            }
        
        return render_template('pages/dashboard/booking_details.html',
                              product_id=product_id,
                              product_status=product_status,
                              booking_info=enriched_info,
                              user=_get_user_info_cached(current_user.id))
                              
    except Exception as e:
        logger.error(f"❌ Erreur détails booking: {str(e)}", exc_info=True)
        flash("❌ Erreur lors du chargement des détails.", "danger")
        return redirect(url_for('dashboard.product_dashboard', product_id=product_id))

# === FONCTIONS UTILITAIRES === #

def _can_cancel_booking(booking_date):
    """Vérifie si une réservation peut être annulée (24h avant)."""
    if not booking_date:
        return False
    
    # Conversion sécurisée en datetime
    if isinstance(booking_date, str):
        try:
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                booking_date = datetime.strptime(booking_date, '%Y-%m-%d')
            except ValueError:
                return False
    elif not isinstance(booking_date, datetime):
        return False
    
    hours_until = (booking_date - datetime.now()).total_seconds() / 3600
    return hours_until >= 24

def _can_reschedule_booking(booking_date):
    """Vérifie si une réservation peut être reprogrammée (48h avant)."""
    if not booking_date:
        return False
    
    # Conversion sécurisée en datetime
    if isinstance(booking_date, str):
        try:
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                booking_date = datetime.strptime(booking_date, '%Y-%m-%d')
            except ValueError:
                return False
    elif not isinstance(booking_date, datetime):
        return False
    
    hours_until = (booking_date - datetime.now()).total_seconds() / 3600
    return hours_until >= 48

def _format_time_until(booking_date):
    """Formate le temps restant avant un rendez-vous."""
    if not booking_date:
        return ""
    
    # Conversion sécurisée
    if isinstance(booking_date, str):
        try:
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                booking_date = datetime.strptime(booking_date, '%Y-%m-%d')
            except ValueError:
                return ""
    elif not isinstance(booking_date, datetime):
        return ""
    
    delta = booking_date - datetime.now()
    
    if delta.total_seconds() <= 0:
        return "Passé"
    
    if delta.days > 0:
        return f"Dans {delta.days} jour{'s' if delta.days > 1 else ''}"
    elif delta.seconds > 3600:
        hours = delta.seconds // 3600
        return f"Dans {hours} heure{'s' if hours > 1 else ''}"
    elif delta.seconds > 60:
        minutes = delta.seconds // 60
        return f"Dans {minutes} minute{'s' if minutes > 1 else ''}"
    else:
        return "Très bientôt"

def _get_preparation_checklist(product_id):
    """Retourne une checklist de préparation selon le produit."""
    checklists = {
        'pack_clarte_fr': [
            "📋 Préparez vos questions sur votre situation personnelle",
            "💡 Réfléchissez à vos objectifs principaux",
            "📱 Vérifiez votre connexion internet pour la visio",
            "🎧 Préparez un casque/écouteurs pour une meilleure qualité",
            "📝 Ayez de quoi prendre des notes importantes"
        ]
    }
    
    return checklists.get(product_id, [
        "📋 Préparez vos questions",
        "📱 Vérifiez votre connexion internet",
        "📝 Préparez de quoi prendre des notes"
    ])

    
def log_user_action(user_id, action, details=None):
    """Log des actions utilisateur pour monitoring."""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        ensure_table_exists('user_actions', '''
            CREATE TABLE IF NOT EXISTS user_actions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                action VARCHAR(100) NOT NULL,
                details JSON,
                ip_address VARCHAR(45),
                user_agent TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user (user_id),
                INDEX idx_action (action),
                INDEX idx_created (created_at)
            )
        ''')
        
        cursor.execute('''
            INSERT INTO user_actions 
            (user_id, action, details, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, action, json.dumps(details) if details else None,
              request.remote_addr, request.user_agent.string))
        
        mysql.connection.commit()
        cursor.close()
        
    except Exception as e:
        logger.error(f"Erreur log action utilisateur: {str(e)}")


@dashboard_bp.app_template_filter('time_until_booking')
def time_until_booking_filter(booking_date):
    """Calcule et formate le temps restant avant un rendez-vous."""
    if not booking_date:
        return ""
    
    # ✅ CORRECTION: Gestion des différents types de dates
    if isinstance(booking_date, str):
        try:
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                booking_date = datetime.strptime(booking_date, '%Y-%m-%d')
            except ValueError:
                logger.warning(f"Format de date non reconnu: {booking_date}")
                return ""
    elif not isinstance(booking_date, datetime):
        logger.warning(f"Type de date non supporté: {type(booking_date)}")
        return ""
    
    now = datetime.now()
    delta = booking_date - now
    
    if delta.total_seconds() <= 0:
        return "Passé"
    
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    if days > 7:
        weeks = days // 7
        return f"Dans {weeks} semaine{'s' if weeks > 1 else ''}"
    elif days > 0:
        return f"Dans {days} jour{'s' if days > 1 else ''}"
    elif hours > 0:
        return f"Dans {hours}h{minutes:02d}"
    elif minutes > 0:
        return f"Dans {minutes} min"
    else:
        return "Maintenant !"

@dashboard_bp.app_template_filter('can_cancel_booking')
def can_cancel_booking_filter(booking_date):
    """Vérifie si une réservation peut être annulée (24h avant)."""
    return _can_cancel_booking(booking_date)

@dashboard_bp.app_template_filter('can_reschedule_booking')
def can_reschedule_booking_filter(booking_date):
    """Vérifie si une réservation peut être reprogrammée (48h avant)."""
    return _can_reschedule_booking(booking_date)

@dashboard_bp.app_template_filter('booking_progress')
def booking_progress_filter(booking_date):
    """Calcule le pourcentage de progression vers un rendez-vous."""
    if not booking_date:
        return 0
    
    # ✅ CORRECTION: Gestion des différents types de dates
    if isinstance(booking_date, str):
        try:
            booking_date = datetime.strptime(booking_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                booking_date = datetime.strptime(booking_date, '%Y-%m-%d')
            except ValueError:
                logger.warning(f"Format de date non reconnu: {booking_date}")
                return 0
    elif not isinstance(booking_date, datetime):
        logger.warning(f"Type de date non supporté: {type(booking_date)}")
        return 0
    
    now = datetime.now()
    
    # Considérer que la "progression" commence 7 jours avant le RDV
    start_period = booking_date - timedelta(days=7)
    
    if now <= start_period:
        return 0
    elif now >= booking_date:
        return 100
    else:
        # Calcul linéaire de la progression
        total_period = (booking_date - start_period).total_seconds()
        elapsed = (now - start_period).total_seconds()
        return min(100, max(0, int((elapsed / total_period) * 100)))

@dashboard_bp.app_template_filter('booking_progress_text')
def booking_progress_text_filter(booking_date):
    """Retourne un texte descriptif de la progression."""
    if not booking_date:
        return ""
    
    progress = booking_progress_filter(booking_date)
    
    if progress == 0:
        return "Programmé"
    elif progress < 25:
        return "Bientôt..."
    elif progress < 50:
        return "Cette semaine"
    elif progress < 75:
        return "Dans peu de temps"
    elif progress < 95:
        return "Très bientôt !"
    else:
        return "C'est parti !"

@dashboard_bp.app_template_filter('format_mysql_time')
def format_mysql_time_filter(time_obj):
    """Filtre template pour formater les temps MySQL."""
    return format_mysql_time(time_obj)

@dashboard_bp.app_template_filter('safe_datetime')
def safe_datetime_filter(date_obj):
    """Filtre pour gérer les dates de manière sécurisée."""
    if not date_obj:
        return ""
    
    if isinstance(date_obj, str):
        return date_obj
    elif isinstance(date_obj, datetime):
        return date_obj.strftime('%Y-%m-%d %H:%M:%S')
    elif hasattr(date_obj, 'strftime'):
        return date_obj.strftime('%Y-%m-%d')
    else:
        return str(date_obj)

def get_user_upcoming_bookings(user_id, limit=10):
    """
    Version corrigée qui récupère TOUS les bookings à venir.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # ✅ REQUÊTE CORRIGÉE - Pas de jointure restrictive avec product_status
        cursor.execute('''
            SELECT 
                b.id, b.booking_id, b.booking_date, b.end_date,
                b.duration_minutes, b.zoom_link, b.status,
                pc.product_id, pc.product_name, 
                pc.emoji, pc.image_url,
                ps.status as order_status,
                ps.id as product_status_id
            FROM bookings b
            JOIN product_catalog pc ON b.product_id = pc.product_id
            LEFT JOIN product_status ps ON (
                b.user_id = ps.user_id 
                AND b.product_id = ps.product_id 
                AND ps.booking_id = b.id  -- ✅ JOINTURE PRÉCISE
            )
            WHERE b.user_id = %s 
              AND b.status IN ('confirmed', 'rescheduled')
              AND b.booking_date > NOW()
            ORDER BY b.booking_date ASC
            LIMIT %s
        ''', (user_id, limit))
        
        bookings = cursor.fetchall()
        
        # Enrichissement des données
        enriched_bookings = []
        for booking in bookings:
            booking_date = booking['booking_date']
            if not isinstance(booking_date, datetime):
                continue
            
            try:
                display_image = booking['image_url'] or booking['emoji'] or '📦'
                
                enriched_booking = {
                    'id': booking['id'],
                    'booking_id': booking['booking_id'],
                    'booking_date': booking_date,
                    'end_date': booking['end_date'],
                    'duration_minutes': booking['duration_minutes'] or 60,
                    'zoom_link': booking['zoom_link'],
                    'status': booking['status'],
                    'product_id': booking['product_id'],
                    'product_name': booking['product_name'],
                    'image_url': display_image,
                    'order_status': booking['order_status'] or 'rdv_planifié',
                    'product_status_id': booking['product_status_id'],
                    
                    # Formatage
                    'formatted_date': format_date_fr(booking_date),
                    'formatted_time': booking_date.strftime('%Hh%M'),
                    'time_until': time_until_booking_filter(booking_date),
                    'can_cancel': _can_cancel_booking(booking_date),
                    'can_reschedule': _can_reschedule_booking(booking_date),
                    'progress_percent': booking_progress_filter(booking_date),
                    'progress_text': booking_progress_text_filter(booking_date),
                    
                    # Calculs temporels
                    'days_until': max(0, (booking_date - datetime.now()).days),
                    'is_today': booking_date.date() == datetime.now().date(),
                    'is_tomorrow': booking_date.date() == (datetime.now() + timedelta(days=1)).date()
                }
                
                enriched_bookings.append(enriched_booking)
                
            except Exception as booking_error:
                logger.error(f"Erreur traitement booking {booking['id']}: {str(booking_error)}")
                continue
        
        return enriched_bookings
        
    except Exception as e:
        logger.error(f"Erreur récupération upcoming bookings: {str(e)}")
        return []
    finally:
        cursor.close()

def get_calendar_days(month_offset=0):
    """
    Génère les données pour un calendrier mensuel avec les rendez-vous.
    CORRECTION: Gestion correcte des dates et mois
    """
    import calendar
    from dateutil.relativedelta import relativedelta  # ✅ Import nécessaire
    
    # Date de référence - CORRECTION
    today = datetime.now()
    
    # ✅ CORRECTION: Utilisation correcte de relativedelta
    if month_offset == 0:
        target_date = today
    else:
        target_date = today + relativedelta(months=month_offset)  # ✅ Au lieu de timedelta
    
    year = target_date.year
    month = target_date.month
    
    # Récupération des rendez-vous du mois
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    bookings_by_day = {}
    
    try:
        # Rendez-vous du mois - REQUÊTE CORRIGÉE
        cursor.execute('''
            SELECT 
                DATE(b.booking_date) as booking_day,
                TIME(b.booking_date) as booking_time,
                pc.product_name,
                pc.emoji as product_emoji,
                ps.status as order_status,
                b.product_id  -- ✅ Ajout pour identifier le produit
            FROM bookings b
            JOIN product_catalog pc ON b.product_id = pc.product_id
            JOIN product_status ps ON (
                b.user_id = ps.user_id 
                AND b.product_id = ps.product_id  -- ✅ Jointure correcte
                AND ps.booking_id = b.id  -- ✅ IMPORTANT: Seulement les bookings assignés
            )
            WHERE b.user_id = %s 
              AND b.status IN ('confirmed', 'rescheduled')
              AND YEAR(b.booking_date) = %s
              AND MONTH(b.booking_date) = %s
            ORDER BY b.booking_date
        ''', (current_user.id if current_user.is_authenticated else 0, year, month))
        
        bookings = cursor.fetchall()
        
        # Organisation par jour
        for booking in bookings:
            day = booking['booking_day'].day
            if day not in bookings_by_day:
                bookings_by_day[day] = []
            
            # Couleur selon le statut
            status_colors = {
                'rdv_planifié': '#667eea',
                'analyse_en_cours': '#f6ad55',
                'livrable_dispo': '#48bb78'
            }
            
            # ✅ CORRECTION: Vérifier le type avant d'appeler strftime
            booking_time_str = ''
            if booking['booking_time']:
                if hasattr(booking['booking_time'], 'strftime'):
                    # C'est un objet datetime ou time
                    booking_time_str = booking['booking_time'].strftime('%H:%M')
                elif isinstance(booking['booking_time'], str):
                    # C'est déjà une chaîne
                    booking_time_str = booking['booking_time']
                else:
                    # C'est un timedelta, on le convertit
                    total_seconds = int(booking['booking_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    booking_time_str = f"{hours:02d}:{minutes:02d}"
            
            bookings_by_day[day].append({
                'time': booking_time_str,
                'title': f"{booking['product_emoji']} {booking['product_name']}",
                'color': status_colors.get(booking['order_status'], '#a0aec0'),
                'product_id': booking['product_id']  # ✅ Pour différencier les produits
            })
    
    except Exception as e:
        logger.error(f"Erreur récupération calendrier: {str(e)}")
    finally:
        cursor.close()
    
    # Génération des jours du calendrier
    cal = calendar.monthcalendar(year, month)
    calendar_days = []
    
    for week in cal:
        for day in week:
            if day == 0:  # Jour du mois précédent/suivant
                continue
                
            day_date = datetime(year, month, day).date()
            
            calendar_days.append({
                'day': day,
                'date': day_date,
                'is_today': day_date == today.date(),
                'is_weekend': day_date.weekday() >= 5,
                'has_booking': day in bookings_by_day,
                'bookings': bookings_by_day.get(day, []),
                'is_past': day_date < today.date()
            })
    
    return calendar_days


@dashboard_bp.route('/api/booking-calendar/<int:month_offset>')
@login_required
def api_booking_calendar(month_offset):
    """API pour récupérer les données du calendrier."""
    try:
        calendar_days = get_calendar_days(month_offset)
        
        # CORRECTION: Calcul correct du nom du mois
        try:
            from dateutil.relativedelta import relativedelta
            target_date = datetime.now() + relativedelta(months=month_offset)
        except ImportError:
            # Fallback
            target_date = datetime.now()
            if month_offset != 0:
                # Approximation simple
                target_date = target_date + timedelta(days=month_offset * 30)
                target_date = target_date.replace(day=1)
        
        month_name = target_date.strftime('%B %Y')
        
        return jsonify({
            'success': True,
            'calendar_days': calendar_days,
            'month_name': month_name,
            'year': target_date.year,
            'month': target_date.month
        })
    except Exception as e:
        logger.error(f"Erreur API calendrier: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def get_booking_statistics(user_id):
    """
    Calcule des statistiques sur les rendez-vous d'un utilisateur.
    ✅ CORRECTION: Gestion d'erreurs renforcée
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Statistiques générales
        cursor.execute('''
            SELECT 
                COUNT(*) as total_bookings,
                COUNT(CASE WHEN status = 'confirmed' AND booking_date > NOW() THEN 1 END) as upcoming,
                COUNT(CASE WHEN status = 'confirmed' AND booking_date < NOW() THEN 1 END) as completed,
                COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled,
                AVG(duration_minutes) as avg_duration,
                MIN(CASE WHEN booking_date > NOW() THEN booking_date END) as next_booking
            FROM bookings 
            WHERE user_id = %s
        ''', (user_id,))
        
        stats = cursor.fetchone()
        
        # Répartition par produit
        cursor.execute('''
            SELECT 
                pc.product_name,
                pc.emoji as product_emoji,
                COUNT(*) as booking_count
            FROM bookings b
            JOIN product_catalog pc ON b.product_id = pc.product_id
            WHERE b.user_id = %s AND b.status != 'cancelled'
            GROUP BY pc.product_id, pc.product_name
            ORDER BY booking_count DESC
        ''', (user_id,))
        
        product_stats = cursor.fetchall()
        
        # ✅ CORRECTION: Gestion sécurisée des valeurs nulles
        total_bookings = stats['total_bookings'] or 0
        completed = stats['completed'] or 0
        
        return {
            'total_bookings': total_bookings,
            'upcoming': stats['upcoming'] or 0,
            'completed': completed,
            'cancelled': stats['cancelled'] or 0,
            'avg_duration': round(stats['avg_duration'] or 60),
            'next_booking': stats['next_booking'],
            'product_breakdown': list(product_stats) if product_stats else [],
            'completion_rate': round((completed / max(1, total_bookings)) * 100, 1) if total_bookings else 0
        }
        
    except Exception as e:
        logger.error(f"Erreur stats booking: {str(e)}")
        return {
            'total_bookings': 0,
            'upcoming': 0,
            'completed': 0,
            'cancelled': 0,
            'avg_duration': 60,
            'next_booking': None,
            'product_breakdown': [],
            'completion_rate': 0
        }
    finally:
        cursor.close()

@dashboard_bp.route('/product/<product_id>/booking/quick-reschedule', methods=['POST'])
@login_required
def quick_reschedule_booking(product_id):
    """
    Reprogrammation rapide via modal depuis le dashboard.
    Interface simplifiée pour changements mineurs.
    """
    logger.info(f"⚡ Quick reschedule - User: {current_user.id}, Product: {product_id}")
    
    try:
        new_date = request.form.get('new_date')
        new_time = request.form.get('new_time')
        
        if not new_date or not new_time:
            return jsonify({'success': False, 'error': 'Date et heure requises'}), 400
        
        # Validation et conversion
        try:
            new_datetime = datetime.strptime(f"{new_date} {new_time}", '%Y-%m-%d %H:%M')
        except ValueError:
            return jsonify({'success': False, 'error': 'Format de date invalide'}), 400
        
        # Vérifications business
        if new_datetime <= datetime.now():
            return jsonify({'success': False, 'error': 'La date doit être dans le futur'}), 400
        
        if new_datetime.weekday() > 4 or new_datetime.hour < 9 or new_datetime.hour >= 18:
            return jsonify({'success': False, 'error': 'Horaires: 9h-18h, lundi-vendredi'}), 400
        
        # Récupération du booking actuel
        booking_info = _get_booking_details(current_user.id, product_id)
        if not booking_info:
            return jsonify({'success': False, 'error': 'Rendez-vous non trouvé'}), 404
        
        # Vérification du délai
        if not _can_reschedule_booking(booking_info['booking_date']):
            return jsonify({'success': False, 'error': 'Trop tard pour reprogrammer'}), 400
        
        # Reprogrammation
        success = reschedule_booking(
            current_user.id,
            product_id,
            booking_info['booking_id'],
            new_datetime,
            new_datetime + timedelta(hours=1)
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Rendez-vous reprogrammé au {format_date_fr(new_datetime)}',
                'new_date': new_datetime.isoformat(),
                'formatted_date': format_date_fr(new_datetime)
            })
        else:
            return jsonify({'success': False, 'error': 'Erreur lors de la reprogrammation'}), 500
            
    except Exception as e:
        logger.error(f"❌ Erreur quick reschedule: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': 'Erreur interne'}), 500

@dashboard_bp.route('/booking/bulk-actions', methods=['POST'])
@login_required
def bulk_booking_actions():
    """
    Actions en masse sur les rendez-vous (utilisateur).
    Permet d'annuler plusieurs RDV ou d'exporter vers calendrier.
    """
    logger.info(f"📋 Bulk booking actions - User: {current_user.id}")
    
    try:
        action = request.form.get('action')
        booking_ids = request.form.getlist('booking_ids')
        
        if not action or not booking_ids:
            flash("❌ Action ou sélection manquante.", "warning")
            return redirect(url_for('dashboard.index'))
        
        results = {'success': 0, 'errors': 0, 'messages': []}
        
        if action == 'bulk_cancel':
            reason = request.form.get('bulk_reason', 'Annulation en masse')
            
            for booking_id in booking_ids:
                # Récupération des infos du booking
                mysql = current_app.mysql
                cursor = mysql.connection.cursor(DictCursor)
                
                try:
                    cursor.execute('''
                        SELECT b.product_id, b.booking_date 
                        FROM bookings b 
                        WHERE b.booking_id = %s AND b.user_id = %s
                    ''', (booking_id, current_user.id))
                    
                    booking = cursor.fetchone()
                    
                    if booking and _can_cancel_booking(booking['booking_date']):
                        success = cancel_booking(current_user.id, booking['product_id'], booking_id)
                        if success:
                            results['success'] += 1
                        else:
                            results['errors'] += 1
                    else:
                        results['errors'] += 1
                        results['messages'].append(f"Impossible d'annuler {booking_id}")
                        
                except Exception as e:
                    logger.error(f"Erreur annulation {booking_id}: {str(e)}")
                    results['errors'] += 1
                finally:
                    cursor.close()
        
        elif action == 'export_calendar':
            # Génération d'un fichier ICS pour import calendrier
            calendar_data = _generate_ics_calendar(current_user.id, booking_ids)
            
            if calendar_data:
                response = make_response(calendar_data)
                response.headers['Content-Type'] = 'text/calendar'
                response.headers['Content-Disposition'] = 'attachment; filename=mes_rdv_Tilto.ics'
                return response
            else:
                flash("❌ Erreur lors de la génération du calendrier.", "danger")
                return redirect(url_for('dashboard.index'))
        
        # Messages de résultat
        if results['success'] > 0:
            flash(f"✅ {results['success']} action(s) réalisée(s) avec succès.", "success")
        
        if results['errors'] > 0:
            flash(f"⚠️ {results['errors']} erreur(s) rencontrée(s).", "warning")
        
        for message in results['messages']:
            flash(message, "info")
            
    except Exception as e:
        logger.error(f"❌ Erreur bulk actions: {str(e)}", exc_info=True)
        flash("❌ Erreur lors des actions en masse.", "danger")
    
    return redirect(url_for('dashboard.index'))

def get_calendar_navigation_info(month_offset=0):
    """Retourne les informations de navigation pour le calendrier."""
    try:
        from dateutil.relativedelta import relativedelta
    except ImportError:
        # Fallback si dateutil n'est pas disponible
        logger.warning("dateutil non disponible, utilisation d'un fallback")
        today = datetime.now()
        # Approximation simple pour les mois
        if month_offset == 0:
            target_date = today
        else:
            # Approximation: 30 jours par mois
            target_date = today + timedelta(days=month_offset * 30)
            # Ajuster au premier du mois
            target_date = target_date.replace(day=1)
    else:
        today = datetime.now()
        target_date = today + relativedelta(months=month_offset)
    
    # ✅ CORRECTION: Calcul sécurisé des mois précédent/suivant
    try:
        from dateutil.relativedelta import relativedelta
        prev_month = target_date - relativedelta(months=1)
        next_month = target_date + relativedelta(months=1)
    except ImportError:
        # Fallback manuel
        if target_date.month == 1:
            prev_month = target_date.replace(year=target_date.year - 1, month=12)
        else:
            prev_month = target_date.replace(month=target_date.month - 1)
        
        if target_date.month == 12:
            next_month = target_date.replace(year=target_date.year + 1, month=1)
        else:
            next_month = target_date.replace(month=target_date.month + 1)
    
    return {
        'current': {
            'year': target_date.year,
            'month': target_date.month,
            'name': target_date.strftime('%B %Y'),
            'short_name': target_date.strftime('%b %Y')
        },
        'previous': {
            'year': prev_month.year,
            'month': prev_month.month,
            'name': prev_month.strftime('%B %Y'),
            'offset': month_offset - 1
        },
        'next': {
            'year': next_month.year,
            'month': next_month.month,
            'name': next_month.strftime('%B %Y'),
            'offset': month_offset + 1
        },
        'is_current_month': month_offset == 0,
        'can_go_back': month_offset > -12,  # Limite à 1 an en arrière
        'can_go_forward': month_offset < 12  # Limite à 1 an en avant
    }

def _generate_ics_calendar(user_id, booking_ids=None):
    """Génère un fichier ICS avec les rendez-vous de l'utilisateur."""
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Construire la requête selon les booking_ids
        if booking_ids:
            placeholders = ','.join(['%s'] * len(booking_ids))
            query = f'''
                SELECT b.booking_date, b.end_date, b.duration_minutes,
                       pc.product_name, pc.emoji as product_emoji,
                       b.zoom_link, b.attendee_email
                FROM bookings b
                JOIN product_catalog pc ON b.product_id = pc.product_id
                WHERE b.user_id = %s AND b.booking_id IN ({placeholders})
                  AND b.status IN ('confirmed', 'rescheduled')
                ORDER BY b.booking_date
            '''
            params = [user_id] + list(booking_ids)
        else:
            query = '''
                SELECT b.booking_date, b.end_date, b.duration_minutes,
                       pc.product_name, pc.emoji as product_emoji,
                       b.zoom_link, b.attendee_email
                FROM bookings b
                JOIN product_catalog pc ON b.product_id = pc.product_id
                WHERE b.user_id = %s AND b.booking_date > NOW()
                  AND b.status IN ('confirmed', 'rescheduled')
                ORDER BY b.booking_date
            '''
            params = [user_id]
        
        cursor.execute(query, params)
        bookings = cursor.fetchall()
        
        if not bookings:
            return None
        
        # Génération du contenu ICS
        ics_content = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Tilto//Dashboard//FR",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH"
        ]
        
        for booking in bookings:
            start_time = booking['booking_date'].strftime('%Y%m%dT%H%M%S')
            
            if booking['end_date']:
                end_time = booking['end_date'].strftime('%Y%m%dT%H%M%S')
            else:
                end_dt = booking['booking_date'] + timedelta(minutes=booking['duration_minutes'] or 60)
                end_time = end_dt.strftime('%Y%m%dT%H%M%S')
            
            # Description enrichie
            description_parts = [f"Consultation {booking['product_name']}"]
            if booking['zoom_link']:
                description_parts.append(f"Lien de connexion: {booking['zoom_link']}")
            description_parts.append("Généré depuis votre dashboard Tilto")
            
            ics_content.extend([
                "BEGIN:VEVENT",
                f"DTSTART:{start_time}",
                f"DTEND:{end_time}",
                f"SUMMARY:{booking['product_emoji']} {booking['product_name']} - Tilto",
                f"DESCRIPTION:{' | '.join(description_parts)}",
                f"UID:Tilto-{user_id}-{booking['booking_date'].strftime('%Y%m%d%H%M%S')}@Tilto.com",
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
                "STATUS:CONFIRMED",
                "END:VEVENT"
            ])
        
        ics_content.append("END:VCALENDAR")
        
        return '\r\n'.join(ics_content)
        
    except Exception as e:
        logger.error(f"Erreur génération ICS: {str(e)}")
        return None
    finally:
        cursor.close()

# === INTÉGRATION DES FONCTIONS DANS LE CONTEXT PROCESSOR === #

@dashboard_bp.app_context_processor
def inject_booking_functions():
    """Injecte les fonctions de gestion des RDV dans tous les templates."""
    return {
        'get_user_upcoming_bookings': get_user_upcoming_bookings,
        'get_calendar_days': get_calendar_days,
        'get_calendar_navigation_info': get_calendar_navigation_info,  # ✅ Ajout
        'get_booking_statistics': get_booking_statistics,
        'time_until_booking': time_until_booking_filter,
        'can_cancel_booking': can_cancel_booking_filter,
        'can_reschedule_booking': can_reschedule_booking_filter,
        'booking_progress': booking_progress_filter,
        'booking_progress_text': booking_progress_text_filter
    }


@dashboard_bp.route('/calendar')
@login_required
def calendar_view():
    """Vue calendrier complète avec navigation."""
    month_offset = request.args.get('month', 0, type=int)
    
    try:
        # Limiter la navigation
        month_offset = max(-12, min(12, month_offset))
        
        calendar_days = get_calendar_days(month_offset)
        navigation_info = get_calendar_navigation_info(month_offset)
        upcoming_bookings = get_user_upcoming_bookings(current_user.id, 10)
        booking_stats = get_booking_statistics(current_user.id)
        
        return render_template('pages/dashboard/calendar.html',
                              calendar_days=calendar_days,
                              navigation=navigation_info,
                              upcoming_bookings=upcoming_bookings,
                              stats=booking_stats,
                              current_month_offset=month_offset,
                              user=_get_user_info_cached(current_user.id))
                              
    except Exception as e:
        logger.error(f"❌ Erreur vue calendrier: {str(e)}", exc_info=True)
        flash("❌ Erreur lors du chargement du calendrier.", "danger")
        return redirect(url_for('dashboard.index'))

# 5. Fonction pour obtenir les créneaux disponibles (pour booking)
def get_available_time_slots(date, product_id):
    """
    Retourne les créneaux disponibles pour une date donnée.
    Utile pour l'interface de réservation.
    """
    if not isinstance(date, datetime):
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d')
        else:
            return []
    
    # Vérifier que c'est un jour ouvrable
    if date.weekday() >= 5:  # Weekend
        return []
    
    # Créneaux de base (9h-18h par tranches d'1h)
    base_slots = []
    for hour in range(9, 18):
        slot_time = date.replace(hour=hour, minute=0, second=0, microsecond=0)
        if slot_time > datetime.now():  # Seulement les créneaux futurs
            base_slots.append(slot_time)
    
    # Récupérer les créneaux déjà pris
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT booking_date 
            FROM bookings 
            WHERE DATE(booking_date) = %s 
            AND status IN ('confirmed', 'rescheduled')
        ''', (date.date(),))
        
        booked_slots = [row['booking_date'] for row in cursor.fetchall()]
        
        # Filtrer les créneaux disponibles
        available_slots = []
        for slot in base_slots:
            is_available = True
            for booked in booked_slots:
                # Vérifier qu'il n'y a pas de conflit (même heure)
                if slot.hour == booked.hour:
                    is_available = False
                    break
            
            if is_available:
                available_slots.append({
                    'datetime': slot,
                    'time_str': slot.strftime('%H:%M'),
                    'display': slot.strftime('%Hh%M'),
                    'value': slot.strftime('%H:%M')
                })
        
        return available_slots
        
    except Exception as e:
        logger.error(f"Erreur créneaux disponibles: {str(e)}")
        return []
    finally:
        cursor.close()

# 6. API pour les créneaux disponibles
@dashboard_bp.route('/api/available-slots/<product_id>')
@login_required
def api_available_slots(product_id):
    """API pour récupérer les créneaux disponibles."""
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({'success': False, 'error': 'Date requise'}), 400
        
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({'success': False, 'error': 'Format de date invalide'}), 400
        
        slots = get_available_time_slots(date, product_id)
        
        return jsonify({
            'success': True,
            'date': date_str,
            'slots': slots,
            'total_available': len(slots)
        })
        
    except Exception as e:
        logger.error(f"Erreur API créneaux: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# === ROUTE POUR WIDGET DASHBOARD === #

@dashboard_bp.route('/api/dashboard-widgets')
@login_required
def api_dashboard_widgets():
    """API pour alimenter les widgets du dashboard en temps réel."""
    try:
        # Données des rendez-vous à venir
        upcoming_bookings = get_user_upcoming_bookings(current_user.id, 5)
        
        # Statistiques
        stats = get_booking_statistics(current_user.id)
        
        # Notifications urgentes
        urgent_notifications = []
        for booking in upcoming_bookings:
            if booking['days_until'] <= 1:
                urgent_notifications.append({
                    'type': 'urgent_booking',
                    'message': f"RDV {booking['product_name']} {booking['time_until']}",
                    'action_url': url_for('dashboard.booking_details', product_id=booking['product_id'])
                })
        
        return jsonify({
            'success': True,
            'upcoming_bookings': upcoming_bookings,
            'stats': stats,
            'urgent_notifications': urgent_notifications,
            'last_updated': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur API widgets: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def assign_booking_to_specific_product(user_id, booking_id, target_order_id):
    """
    Assigne manuellement un booking à un produit spécifique.
    Utile pour résoudre les ambiguïtés.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        mysql.connection.begin()
        
        # Récupérer les informations du booking
        cursor.execute('''
            SELECT b.id, b.product_id, b.booking_date 
            FROM bookings b 
            WHERE b.booking_id = %s AND b.user_id = %s
        ''', (booking_id, user_id))
        
        booking = cursor.fetchone()
        if not booking:
            return False
        
        # Récupérer le produit cible
        cursor.execute('''
            SELECT ps.id FROM product_status ps
            JOIN orders o ON ps.user_id = o.user_id
            JOIN order_product op ON o.order_id = op.order_id AND ps.product_id = op.product_id
            WHERE o.order_id = %s AND ps.user_id = %s AND ps.product_id = %s
        ''', (target_order_id, user_id, booking['product_id']))
        
        product_status = cursor.fetchone()
        if not product_status:
            return False
        
        # Désassigner le booking des autres produits du même type
        cursor.execute('''
            UPDATE product_status 
            SET booking_id = NULL, status = 'achat_confirmé'
            WHERE user_id = %s AND product_id = %s AND booking_id = %s
        ''', (user_id, booking['product_id'], booking['id']))
        
        # Assigner le booking au produit cible
        cursor.execute('''
            UPDATE product_status 
            SET booking_id = %s, status = 'rdv_planifié', updated_at = NOW()
            WHERE id = %s
        ''', (booking['id'], product_status['id']))
        
        mysql.connection.commit()
        logger.info(f"✅ Booking {booking_id} assigné au produit order {target_order_id}")
        return True
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"❌ Erreur assignation booking: {str(e)}")
        return False
    finally:
        cursor.close()


# === CORRECTION 3: Route d'administration pour résoudre les conflits ===

@dashboard_bp.route('/admin/resolve-booking-conflicts')
@admin_required
def admin_resolve_booking_conflicts():
    """
    Interface admin pour résoudre les conflits de bookings.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Identifier les conflits potentiels
        cursor.execute('''
            SELECT 
                b.booking_id,
                b.product_id,
                b.booking_date,
                COUNT(DISTINCT o.order_id) as order_count,
                GROUP_CONCAT(DISTINCT o.order_id) as order_ids,
                GROUP_CONCAT(DISTINCT u.email) as user_emails
            FROM bookings b
            JOIN orders o ON EXISTS (
                SELECT 1 FROM order_product op 
                WHERE op.order_id = o.order_id 
                AND op.product_id = b.product_id
            )
            JOIN users u ON o.user_id = u.user_id
            WHERE b.status IN ('confirmed', 'rescheduled')
            GROUP BY b.booking_id, b.product_id, b.booking_date
            HAVING order_count > 1
            ORDER BY b.booking_date DESC
        ''')
        
        conflicts = cursor.fetchall()
        
        return render_template('admin/booking_conflicts.html', conflicts=conflicts)
        
    except Exception as e:
        logger.error(f"❌ Erreur résolution conflits: {str(e)}")
        flash("Erreur lors du chargement des conflits.", "danger")
        return redirect(url_for('dashboard.admin_orders'))
    finally:
        cursor.close()


# === CORRECTION 4: API pour assignation rapide ===

@dashboard_bp.route('/api/assign-booking', methods=['POST'])
@login_required
def api_assign_booking():
    """
    API pour assigner un booking à un produit spécifique.
    """
    try:
        data = request.get_json()
        booking_id = data.get('booking_id')
        order_id = data.get('order_id')
        
        if not booking_id or not order_id:
            return jsonify({'success': False, 'error': 'Paramètres manquants'}), 400
        
        success = assign_booking_to_specific_product(
            user_id=current_user.id,
            booking_id=booking_id,
            target_order_id=order_id
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Booking assigné avec succès'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Échec de l\'assignation'
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Erreur API assign booking: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# === REQUÊTE SQL POUR DÉBOGUER VOS DONNÉES ===

"""
Pour comprendre votre situation actuelle, exécutez cette requête :

SELECT 
    'ORDERS' as table_name,
    o.order_id,
    o.user_id,
    o.created_at,
    NULL as product_id,
    NULL as booking_date,
    o.status
FROM orders o 
WHERE o.user_id = 1

UNION ALL

SELECT 
    'ORDER_PRODUCT' as table_name,
    op.order_id,
    NULL as user_id,
    op.created_at,
    op.product_id,
    NULL as booking_date,
    NULL as status
FROM order_product op
JOIN orders o ON op.order_id = o.order_id
WHERE o.user_id = 1

UNION ALL

SELECT 
    'PRODUCT_STATUS' as table_name,
    NULL as order_id,
    ps.user_id,
    ps.created_at,
    ps.product_id,
    NULL as booking_date,
    ps.status
FROM product_status ps
WHERE ps.user_id = 1

UNION ALL

SELECT 
    'BOOKINGS' as table_name,
    NULL as order_id,
    b.user_id,
    b.created_at,
    b.product_id,
    b.booking_date,
    b.status
FROM bookings b
WHERE b.user_id = 1

ORDER BY table_name, created_at;

Cette requête vous montrera toutes vos données liées pour comprendre les relations.
"""

# === API POUR LA GESTION DES BOOKINGS (Interface Admin) ===

@dashboard_bp.route('/api/bookings/<product_id>/<int:user_id>')
@admin_required
def api_get_bookings(product_id, user_id):
    """
    API pour récupérer tous les bookings d'un produit/utilisateur.
    Utilisée par l'interface admin pour la gestion des bookings.
    """
    logger.info(f"🔍 API get bookings - Product: {product_id}, User: {user_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer tous les bookings pour ce produit/utilisateur
        cursor.execute('''
            SELECT 
                b.id,
                b.booking_id,
                b.booking_date,
                b.end_date,
                b.duration_minutes,
                b.attendee_email,
                b.attendee_name,
                b.zoom_link,
                b.status,
                b.created_at,
                ps.id as assigned_order_id
            FROM bookings b
            LEFT JOIN product_status ps ON (
                b.id = ps.booking_id 
                AND ps.user_id = %s 
                AND ps.product_id = %s
            )
            WHERE b.user_id = %s 
            AND b.product_id = %s
            AND b.status IN ('confirmed', 'rescheduled')
            ORDER BY b.booking_date DESC
        ''', (user_id, product_id, user_id, product_id))
        
        bookings_raw = cursor.fetchall()
        
        # Enrichir les données
        bookings = []
        for booking in bookings_raw:
            bookings.append({
                'id': booking['id'],
                'booking_id': booking['booking_id'],
                'booking_date': booking['booking_date'].isoformat() if booking['booking_date'] else None,
                'formatted_date': format_date_fr(booking['booking_date']) if booking['booking_date'] else '',
                'end_date': booking['end_date'].isoformat() if booking['end_date'] else None,
                'duration_minutes': booking['duration_minutes'] or 60,
                'attendee_email': booking['attendee_email'],
                'attendee_name': booking['attendee_name'],
                'zoom_link': booking['zoom_link'],
                'status': booking['status'],
                'assigned_order_id': booking['assigned_order_id'],
                'is_assigned': booking['assigned_order_id'] is not None,
                'created_at': booking['created_at'].isoformat() if booking['created_at'] else None
            })
        
        return jsonify({
            'success': True,
            'bookings': bookings,
            'total_count': len(bookings)
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur API get bookings: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Erreur lors de la récupération des bookings'
        }), 500
    finally:
        cursor.close()


@dashboard_bp.route('/api/unassign-booking', methods=['POST'])
@admin_required
def api_unassign_booking():
    """
    API pour désassigner un booking d'une commande.
    """
    logger.info(f"🔗 API unassign booking - Admin: {current_user.id}")
    
    try:
        data = request.get_json()
        booking_id = data.get('booking_id')
        order_id = data.get('order_id')
        
        if not booking_id:
            return jsonify({'success': False, 'error': 'Booking ID manquant'}), 400
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Récupérer les informations du booking
            cursor.execute('''
                SELECT b.id, b.user_id, b.product_id 
                FROM bookings b 
                WHERE b.booking_id = %s
            ''', (booking_id,))
            
            booking = cursor.fetchone()
            if not booking:
                return jsonify({'success': False, 'error': 'Booking non trouvé'}), 404
            
            # Désassigner le booking
            cursor.execute('''
                UPDATE product_status 
                SET booking_id = NULL, status = 'achat_confirmé', updated_at = NOW()
                WHERE user_id = %s AND product_id = %s AND booking_id = %s
            ''', (booking['user_id'], booking['product_id'], booking['id']))
            
            # Log de l'action
            cursor.execute('''
                INSERT INTO product_status_updates
                (order_id, user_id, product_id, old_status, new_status, 
                 booking_id, admin_id, admin_note, update_type)
                SELECT ps.id, %s, %s, 'rdv_planifié', 'achat_confirmé', 
                       NULL, %s, %s, 'manual'
                FROM product_status ps 
                WHERE ps.user_id = %s AND ps.product_id = %s
                LIMIT 1
            ''', (
                booking['user_id'], booking['product_id'], current_user.id,
                f"Booking {booking_id} désassigné par admin",
                booking['user_id'], booking['product_id']
            ))
            
            mysql.connection.commit()
            
            return jsonify({
                'success': True,
                'message': 'Booking désassigné avec succès'
            })
            
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur API unassign booking: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Erreur lors de la désassignation'
        }), 500


@dashboard_bp.route('/api/create-manual-booking', methods=['POST'])
@admin_required
def api_create_manual_booking():
    """
    API pour créer un booking manuel depuis l'interface admin.
    """
    logger.info(f"➕ API create manual booking - Admin: {current_user.id}")
    
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        product_id = data.get('product_id')
        user_id = data.get('user_id')
        booking_datetime_str = data.get('booking_datetime')
        attendee_email = data.get('attendee_email', '')
        
        # Validation des données
        if not all([order_id, product_id, user_id, booking_datetime_str]):
            return jsonify({'success': False, 'error': 'Paramètres manquants'}), 400
        
        # Conversion de la date
        try:
            booking_datetime = datetime.strptime(booking_datetime_str, '%Y-%m-%d %H:%M')
        except ValueError:
            return jsonify({'success': False, 'error': 'Format de date invalide (YYYY-MM-DD HH:MM)'}), 400
        
        # Vérification que la date est dans le futur
        if booking_datetime <= datetime.now():
            return jsonify({'success': False, 'error': 'La date doit être dans le futur'}), 400
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            # Vérifier que l'utilisateur a bien acheté ce produit
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM orders o
                JOIN order_product op ON o.order_id = op.order_id
                WHERE o.user_id = %s AND op.product_id = %s AND o.status = 'paid'
            ''', (user_id, product_id))
            
            access_check = cursor.fetchone()
            if not access_check or access_check['count'] == 0:
                return jsonify({'success': False, 'error': 'Utilisateur sans accès à ce produit'}), 403
            
            # Créer le booking manuel
            external_booking_id = f"admin-{current_user.id}-{int(time.time())}"
            
            booking_db_id = create_or_update_booking(
                user_id=user_id,
                product_id=product_id,
                external_booking_id=external_booking_id,
                start_datetime=booking_datetime,
                end_datetime=booking_datetime + timedelta(hours=1),
                duration=60,
                attendee_email=attendee_email or f"user_{user_id}@manual.booking",
                attendee_name=f"Booking manuel créé par admin {current_user.username}",
                answers={'source': 'admin_manual', 'created_by': current_user.id}
            )
            
            if booking_db_id:
                mysql.connection.commit()
                
                return jsonify({
                    'success': True,
                    'message': 'Booking manuel créé avec succès',
                    'booking_id': external_booking_id,
                    'internal_id': booking_db_id,
                    'booking_date': booking_datetime.isoformat()
                })
            else:
                return jsonify({'success': False, 'error': 'Erreur lors de la création du booking'}), 500
                
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur API create manual booking: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Erreur lors de la création du booking'
        }), 500


@dashboard_bp.route('/api/booking-conflicts')
@admin_required
def api_booking_conflicts():
    """
    API pour récupérer les conflits de bookings.
    """
    logger.info(f"⚠️ API booking conflicts - Admin: {current_user.id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Rechercher les conflits potentiels
        cursor.execute('''
            SELECT 
                b.booking_id,
                b.product_id,
                b.booking_date,
                b.user_id,
                pc.product_name,
                COUNT(DISTINCT ps.id) as status_count,
                GROUP_CONCAT(DISTINCT ps.id) as order_ids,
                GROUP_CONCAT(DISTINCT u.email) as user_emails
            FROM bookings b
            JOIN product_catalog pc ON b.product_id = pc.product_id
            JOIN users u ON b.user_id = u.user_id
            LEFT JOIN product_status ps ON (
                ps.user_id = b.user_id 
                AND ps.product_id = b.product_id
            )
            WHERE b.status IN ('confirmed', 'rescheduled')
            GROUP BY b.booking_id, b.product_id, b.booking_date, b.user_id, pc.product_name
            HAVING status_count > 1 OR status_count = 0
            ORDER BY b.booking_date DESC
        ''')
        
        conflicts_raw = cursor.fetchall()
        
        # Enrichir les données des conflits
        conflicts = []
        for conflict in conflicts_raw:
            conflicts.append({
                'booking_id': conflict['booking_id'],
                'product_id': conflict['product_id'],
                'product_name': conflict['product_name'],
                'user_id': conflict['user_id'],
                'booking_date': conflict['booking_date'].isoformat() if conflict['booking_date'] else None,
                'formatted_date': format_date_fr(conflict['booking_date']) if conflict['booking_date'] else '',
                'status_count': conflict['status_count'],
                'order_ids': conflict['order_ids'] or '',
                'user_emails': conflict['user_emails'] or '',
                'conflict_type': 'multiple_orders' if conflict['status_count'] > 1 else 'no_assignment'
            })
        
        return jsonify({
            'success': True,
            'conflicts': conflicts,
            'total_conflicts': len(conflicts)
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur API booking conflicts: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Erreur lors de la récupération des conflits'
        }), 500
    finally:
        cursor.close()


@dashboard_bp.route('/api/order-statuses')
@admin_required
def api_order_statuses():
    """
    API pour la mise à jour en temps réel des statuts de commandes.
    """
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        cursor.execute('''
            SELECT 
                ps.id as order_id,
                ps.status,
                ps.updated_at
            FROM product_status ps
            WHERE ps.updated_at >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
            ORDER BY ps.updated_at DESC
        ''')
        
        recent_updates = cursor.fetchall()
        
        # Enrichir avec les informations de statut
        orders = []
        for update in recent_updates:
            status_info = ORDER_STATUSES.get(update['status'], ORDER_STATUSES['achat_confirmé'])
            orders.append({
                'order_id': update['order_id'],
                'status': update['status'],
                'status_label': status_info['label'],
                'status_color': status_info['color'],
                'updated_at': update['updated_at'].isoformat()
            })
        
        cursor.close()
        
        return jsonify({
            'success': True,
            'orders': orders,
            'last_update': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur API order statuses: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# === FONCTION UTILITAIRE POUR L'INTERFACE ADMIN ===

def get_admin_dashboard_stats():
    """
    Calcule les statistiques pour le dashboard admin.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Statistiques principales
        cursor.execute('''
            SELECT 
                COUNT(*) as total_orders,
                COUNT(CASE WHEN status = 'achat_confirmé' THEN 1 END) as pending_bookings,
                COUNT(CASE WHEN status = 'rdv_planifié' THEN 1 END) as scheduled_appointments,
                COUNT(CASE WHEN status = 'livrable_dispo' THEN 1 END) as ready_deliverables,
                COUNT(CASE WHEN status = 'post_livraison' THEN 1 END) as completed_orders
            FROM product_status
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        ''')
        
        stats = cursor.fetchone()
        return stats or {
            'total_orders': 0,
            'pending_bookings': 0,
            'scheduled_appointments': 0,
            'ready_deliverables': 0,
            'completed_orders': 0
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur stats admin: {str(e)}")
        return {
            'total_orders': 0,
            'pending_bookings': 0,
            'scheduled_appointments': 0,
            'ready_deliverables': 0,
            'completed_orders': 0
        }
    finally:
        cursor.close()

def format_mysql_time(time_obj):
    """
    Formate un objet time/timedelta de MySQL en chaîne HH:MM
    """
    if not time_obj:
        return ''
    
    if hasattr(time_obj, 'strftime'):
        # C'est un objet datetime ou time
        return time_obj.strftime('%H:%M')
    elif isinstance(time_obj, str):
        # C'est déjà une chaîne
        return time_obj
    elif hasattr(time_obj, 'total_seconds'):
        # C'est un timedelta
        total_seconds = int(time_obj.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    else:
        # Type inconnu, retourner une chaîne vide
        logger.warning(f"Type d'objet temps inconnu: {type(time_obj)}")
        return ''

def safe_get_calendar_days(month_offset=0):
    """
    Version sécurisée de get_calendar_days avec gestion d'erreurs.
    """
    try:
        return get_calendar_days(month_offset)
    except Exception as e:
        logger.error(f"Erreur get_calendar_days: {str(e)}")
        return []

def safe_get_calendar_navigation_info(month_offset=0):
    """
    Version sécurisée de get_calendar_navigation_info.
    """
    try:
        return get_calendar_navigation_info(month_offset)
    except Exception as e:
        logger.error(f"Erreur get_calendar_navigation_info: {str(e)}")
        today = datetime.now()
        return {
            'current': {
                'year': today.year,
                'month': today.month,
                'name': today.strftime('%B %Y'),
                'short_name': today.strftime('%b %Y')
            },
            'previous': {'offset': month_offset - 1},
            'next': {'offset': month_offset + 1},
            'is_current_month': month_offset == 0,
            'can_go_back': True,
            'can_go_forward': True
        }

def safe_get_booking_statistics(user_id):
    """
    Version sécurisée de get_booking_statistics.
    """
    try:
        return get_booking_statistics(user_id)
    except Exception as e:
        logger.error(f"Erreur get_booking_statistics: {str(e)}")
        return {
            'total_bookings': 0,
            'upcoming': 0,
            'completed': 0,
            'cancelled': 0,
            'avg_duration': 60,
            'next_booking': None,
            'product_breakdown': [],
            'completion_rate': 0
        }

@dashboard_bp.route('/api/status/<product_id>')
@login_required  
def api_get_product_status(product_id):
    """API pour récupérer le statut d'un produit."""
    try:
        status = get_user_product_status(current_user.id, product_id)
        
        if not status:
            return jsonify({'error': 'Produit non trouvé'}), 404
        
        return jsonify({
            'success': True,
            'status': status['status'],
            'status_info': ORDER_STATUSES.get(status['status'], {}),
            'last_updated': status['updated_at'].isoformat() if status.get('updated_at') else None,
            'status_changed': False  # Pour les mises à jour en temps réel
        })
        
    except Exception as e:
        logger.error(f"❌ Erreur API status: {str(e)}")
        return jsonify({'error': 'Erreur interne'}), 500

@dashboard_bp.route('/product-status/<int:status_id>')
@login_required
def product_dashboard_by_status(status_id):
    """Dashboard produit par ID de statut (plus précis)."""
    logger.info(f"📦 Product dashboard by status - User: {current_user.id}, Status ID: {status_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # ✅ VÉRIFICATION D'ACCÈS par status_id
        cursor.execute('''
            SELECT 
                ps.id, ps.user_id, ps.order_id, ps.product_id, ps.status,
                ps.livrable_date, ps.created_at, ps.updated_at, ps.booking_id,
                o.order_number, o.created_at as purchase_date,
                pc.product_name, pc.subtitle as description, 
                pc.emoji, pc.image_url,
                b.booking_id as external_booking_id, b.booking_date, b.zoom_link
            FROM product_status ps
            JOIN orders o ON ps.order_id = o.order_id
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            LEFT JOIN bookings b ON ps.booking_id = b.id
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        product_status = cursor.fetchone()
        
        if not product_status:
            flash("Vous n'avez pas accès à ce produit.", "danger")
            return redirect(url_for('dashboard.index'))
        
        # ✅ CONSTRUCTION des données produit
        display_image = product_status['image_url'] or product_status['emoji'] or '📦'
        
        product_enriched = {
            'id': product_status['product_id'],
            'name': product_status['product_name'],
            'description': product_status['description'],
            'image': get_product_display_image_html(product_status),
            'purchase_date': product_status['purchase_date'],
            'order_id': product_status['order_id'],
            'order_number': product_status['order_number']
        }
        
        # ✅ INFORMATIONS de réservation
        booking_info = None
        if product_status['status'] in ['rdv_planifié', 'analyse_en_cours', 'livrable_dispo', 'post_livraison']:
            if product_status['booking_id']:
                booking_info = {
                    'id': product_status['booking_id'],
                    'booking_id': product_status['external_booking_id'],
                    'booking_date': product_status['booking_date'],
                    'zoom_link': product_status['zoom_link'],
                    'duration_minutes': 60,  # Par défaut
                    'formatted_date': format_date_fr(product_status['booking_date']) if product_status['booking_date'] else None
                }
        
        # ✅ CONFIGURATION de l'interface
        ui_config = {
            'can_book': product_status['status'] == 'achat_confirmé',
            'show_booking_widget': product_status['status'] == 'achat_confirmé',
            'show_booking_details': booking_info is not None,
            'can_download': product_status['status'] in ['livrable_dispo', 'post_livraison'],
            'can_give_feedback': product_status['status'] == 'livrable_dispo',
            'process_completed': product_status['status'] == 'post_livraison'
        }
        
        # ✅ STATUT avec informations visuelles
        current_status = product_status['status']
        status_info = ORDER_STATUSES.get(current_status, ORDER_STATUSES['achat_confirmé'])
        
        # ✅ TIMELINE du processus
        timeline = _build_product_timeline(dict(product_status), booking_info)
        
        logger.info(f"📋 Product loaded by status - Status: {current_status}, UI Config: {ui_config}")
        
        return render_template('pages/dashboard/product.html', 
                              product=product_enriched,
                              status=current_status,
                              status_info=status_info,
                              product_status=dict(product_status),
                              booking_info=booking_info,
                              ui_config=ui_config,
                              timeline=timeline,
                              user=_get_user_info_cached(current_user.id),
                              now=datetime.now(),
                              timedelta=timedelta)
                              
    except Exception as e:
        logger.error(f"❌ Erreur product dashboard by status: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du chargement du produit.", "danger")
        return redirect(url_for('dashboard.index'))
    finally:
        cursor.close()

def get_product_display_image_html(product_data):
    """Génère le HTML d'affichage pour l'image produit."""
    image_url = product_data.get('image_url', '').strip()
    emoji = product_data.get('emoji', '').strip()
    product_name = product_data.get('product_name', 'Produit')
    
    if image_url and ('http' in image_url or image_url.startswith('/')):
        return f'<div class="product-image"><img src="{image_url}" alt="{product_name}" style="width: 100px; height: 100px; object-fit: cover; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);"></div>'
    elif emoji:
        return f'<div class="product-emoji" style="font-size: 4rem; text-align: center;">{emoji}</div>'
    else:
        return '<div class="product-emoji" style="font-size: 4rem; text-align: center;">📦</div>'


# ✅ AJOUTEZ CES ROUTES À LA FIN DE VOTRE FICHIER dashboard.py
# (après la dernière fonction existante)

@dashboard_bp.route('/product-status/<int:status_id>/booking/details')
@login_required  
def booking_details_by_status(status_id):
    """
    Affichage détaillé des informations de rendez-vous par status_id.
    """
    logger.info(f"📋 Booking details by status - User: {current_user.id}, Status ID: {status_id}")
    
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer le product_status avec vérification d'accès
        cursor.execute('''
            SELECT 
                ps.id, ps.user_id, ps.product_id, ps.status,
                pc.product_name, pc.subtitle as description
            FROM product_status ps
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        product_status = cursor.fetchone()
        cursor.close()
        
        if not product_status:
            flash("❌ Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.index'))
        
        # Utiliser la fonction existante avec product_id
        booking_info = _get_booking_details(current_user.id, product_status['product_id'])
        
        # Enrichir les informations comme dans la fonction originale
        enriched_info = None
        if booking_info:
            enriched_info = {
                **booking_info,
                'can_cancel': _can_cancel_booking(booking_info['booking_date']),
                'can_reschedule': _can_reschedule_booking(booking_info['booking_date']),
                'calendar_link': _generate_calendar_link(booking_info['booking_date'], 
                                                       product_status.get('product_name', 'Rendez-vous Tilto')),
                'time_until_booking': _format_time_until(booking_info['booking_date']),
                'preparation_checklist': _get_preparation_checklist(product_status['product_id'])
            }
        
        return render_template('pages/dashboard/booking_details.html',
                              product_id=product_status['product_id'],
                              product_status=dict(product_status),
                              booking_info=enriched_info,
                              user=_get_user_info_cached(current_user.id))
                              
    except Exception as e:
        logger.error(f"❌ Erreur détails booking by status: {str(e)}", exc_info=True)
        flash("❌ Erreur lors du chargement des détails.", "danger")
        return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/product-status/<int:status_id>/booking/cancel', methods=['POST'])
@login_required
def cancel_user_booking_by_status(status_id):
    """Annulation d'un rendez-vous par status_id."""
    logger.info(f"❌ User booking cancellation by status - User: {current_user.id}, Status ID: {status_id}")
    
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer le product_id depuis status_id
        cursor.execute('''
            SELECT ps.product_id
            FROM product_status ps
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            flash("❌ Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.index'))
        
        product_id = result['product_id']
        reason = request.form.get('reason', '').strip()
        
        # Récupération des informations de réservation
        product_status = get_user_product_status(current_user.id, product_id)
        if not product_status or product_status.get('status') != 'rdv_planifié':
            flash("❌ Aucun rendez-vous à annuler pour ce produit.", "warning")
            return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
        
        booking_info = _get_booking_details(current_user.id, product_id)
        if not booking_info:
            flash("❌ Informations de rendez-vous introuvables.", "danger")
            return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
        
        # Vérification du délai d'annulation (min 24h avant)
        booking_date = booking_info['booking_date']
        hours_until_booking = (booking_date - datetime.now()).total_seconds() / 3600
        
        if hours_until_booking < 24:
            flash("⚠️ Impossible d'annuler un rendez-vous moins de 24h avant. Contactez notre équipe.", "warning")
            return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
        
        # Annulation
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            mysql.connection.begin()
            
            success = cancel_booking(current_user.id, product_id, booking_info['booking_id'])
            
            if success:
                cursor.execute('''
                    INSERT INTO user_booking_actions 
                    (user_id, product_id, booking_id, action_type, reason, created_at)
                    VALUES (%s, %s, %s, 'cancel', %s, NOW())
                    ON DUPLICATE KEY UPDATE id=id
                ''', (current_user.id, product_id, booking_info['booking_id'], reason))
                
                _notify_team_booking_cancellation(current_user.id, product_id, booking_date, reason)
                
                mysql.connection.commit()
                flash("✅ Votre rendez-vous a été annulé avec succès. Vous pouvez programmer un nouveau créneau.", "success")
                logger.info(f"User booking cancelled - User: {current_user.id}, Booking: {booking_info['booking_id']}")
                
            else:
                flash("❌ Erreur lors de l'annulation. Veuillez réessayer.", "danger")
                
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"❌ Erreur annulation utilisateur by status: {str(e)}", exc_info=True)
        flash("❌ Une erreur est survenue lors de l'annulation.", "danger")
    
    return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))


@dashboard_bp.route('/product-status/<int:status_id>/booking/reschedule', methods=['GET', 'POST'])
@login_required
def reschedule_user_booking_by_status(status_id):
    """Reprogrammation d'un rendez-vous par status_id."""
    logger.info(f"🔄 User booking reschedule by status - User: {current_user.id}, Status ID: {status_id}")
    
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer le product_id depuis status_id
        cursor.execute('''
            SELECT ps.product_id
            FROM product_status ps
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            flash("❌ Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.index'))
        
        product_id = result['product_id']
        
        # Vérifications préliminaires
        product_status = get_user_product_status(current_user.id, product_id)
        if not product_status or product_status.get('status') != 'rdv_planifié':
            flash("❌ Aucun rendez-vous à reprogrammer pour ce produit.", "warning")
            return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
        
        booking_info = _get_booking_details(current_user.id, product_id)
        if not booking_info:
            flash("❌ Informations de rendez-vous introuvables.", "danger")
            return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
        
        # Vérification du délai de reprogrammation (min 48h avant)
        booking_date = booking_info['booking_date']
        hours_until_booking = (booking_date - datetime.now()).total_seconds() / 3600
        
        if hours_until_booking < 48:
            flash("⚠️ Impossible de reprogrammer un rendez-vous moins de 48h avant. Contactez notre équipe.", "warning")
            return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
        
        if request.method == 'GET':
            # Affichage de l'interface de reprogrammation
            return render_template('pages/dashboard/reschedule_booking.html',
                                  product_id=product_id,
                                  status_id=status_id,
                                  current_booking=booking_info,
                                  product_status=product_status,
                                  user=_get_user_info_cached(current_user.id))
        
        # POST - Traitement de la reprogrammation
        try:
            new_date_str = request.form.get('new_date', '').strip()
            new_time_str = request.form.get('new_time', '').strip()
            reason = request.form.get('reason', '').strip()
            
            if not new_date_str or not new_time_str:
                flash("❌ Veuillez sélectionner une nouvelle date et heure.", "warning")
                return redirect(url_for('dashboard.reschedule_user_booking_by_status', status_id=status_id))
            
            # Conversion de la nouvelle date/heure
            try:
                new_datetime_str = f"{new_date_str} {new_time_str}"
                new_datetime = datetime.strptime(new_datetime_str, '%Y-%m-%d %H:%M')
                
                # Vérification que la nouvelle date est dans le futur
                if new_datetime <= datetime.now():
                    flash("❌ La nouvelle date doit être dans le futur.", "warning")
                    return redirect(url_for('dashboard.reschedule_user_booking_by_status', status_id=status_id))
                
                # Vérification des heures ouvrables (9h-18h, lundi-vendredi)
                if new_datetime.weekday() > 4 or new_datetime.hour < 9 or new_datetime.hour >= 18:
                    flash("⚠️ Veuillez choisir un créneau pendant les heures ouvrables (9h-18h, lundi-vendredi).", "warning")
                    return redirect(url_for('dashboard.reschedule_user_booking_by_status', status_id=status_id))
                    
            except ValueError:
                flash("❌ Format de date/heure invalide.", "danger")
                return redirect(url_for('dashboard.reschedule_user_booking_by_status', status_id=status_id))
            
            mysql = current_app.mysql
            cursor = mysql.connection.cursor(DictCursor)
            
            try:
                mysql.connection.begin()
                
                # Reprogrammation
                success = reschedule_booking(
                    current_user.id, 
                    product_id, 
                    booking_info['booking_id'], 
                    new_datetime,
                    new_datetime + timedelta(hours=1)
                )
                
                if success:
                    # Log de la reprogrammation
                    cursor.execute('''
                        INSERT INTO user_booking_actions 
                        (user_id, product_id, booking_id, action_type, reason, new_datetime, created_at)
                        VALUES (%s, %s, %s, 'reschedule', %s, %s, NOW())
                        ON DUPLICATE KEY UPDATE id=id
                    ''', (current_user.id, product_id, booking_info['booking_id'], reason, new_datetime))
                    
                    # Notifications
                    _notify_team_booking_reschedule(current_user.id, product_id, booking_date, new_datetime, reason)
                    send_rdv_confirmation_email(current_user.id, new_datetime, product_id)
                    
                    mysql.connection.commit()
                    
                    flash(f"✅ Votre rendez-vous a été reprogrammé au {format_date_fr(new_datetime)}.", "success")
                    logger.info(f"User booking rescheduled - User: {current_user.id}, New date: {new_datetime}")
                    
                    return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))
                    
                else:
                    flash("❌ Erreur lors de la reprogrammation. Veuillez réessayer.", "danger")
                    
            except Exception as e:
                mysql.connection.rollback()
                raise e
            finally:
                cursor.close()
                
        except Exception as e:
            logger.error(f"❌ Erreur reprogrammation utilisateur by status: {str(e)}", exc_info=True)
            flash("❌ Une erreur est survenue lors de la reprogrammation.", "danger")
        
    except Exception as e:
        logger.error(f"❌ Erreur reprogrammation by status: {str(e)}", exc_info=True)
        flash("❌ Une erreur est survenue.", "danger")
    
    return redirect(url_for('dashboard.product_dashboard_by_status', status_id=status_id))


@dashboard_bp.route('/product-status/<int:status_id>/download-pdf')
@login_required
def download_pdf_by_status(status_id):
    """Téléchargement sécurisé du livrable PDF par status_id."""
    logger.info(f"📥 PDF download by status - User: {current_user.id}, Status ID: {status_id}")
    
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer le product_id depuis status_id
        cursor.execute('''
            SELECT ps.product_id
            FROM product_status ps
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            flash("❌ Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.index'))
        
        product_id = result['product_id']
        
        # Utiliser la fonction existante
        return download_pdf(product_id)
        
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement PDF by status: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors du téléchargement.", "danger")
        return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/product-status/<int:status_id>/feedback', methods=['POST'])
@login_required
def submit_feedback_by_status(status_id):
    """Soumission de feedback utilisateur par status_id."""
    logger.info(f"💬 Feedback submission by status - User: {current_user.id}, Status ID: {status_id}")
    
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        # Récupérer le product_id depuis status_id
        cursor.execute('''
            SELECT ps.product_id
            FROM product_status ps
            WHERE ps.id = %s AND ps.user_id = %s
        ''', (status_id, current_user.id))
        
        result = cursor.fetchone()
        cursor.close()
        
        if not result:
            flash("❌ Produit non trouvé.", "danger")
            return redirect(url_for('dashboard.index'))
        
        product_id = result['product_id']
        
        # Utiliser la fonction existante
        return submit_feedback(product_id)
        
    except Exception as e:
        logger.error(f"❌ Erreur feedback by status: {str(e)}", exc_info=True)
        flash("Une erreur est survenue lors de l'enregistrement.", "danger")
        return redirect(url_for('dashboard.index'))

@dashboard_bp.route('/webhook/youcanbook', methods=['POST'])
@csrf.exempt
def youcanbook_webhook():
    """Webhook YouCanBookMe pour traiter les réservations."""
    logger.info("🔔 Webhook YouCanBookMe reçu")
    
    try:
        webhook_data = request.get_json() or {}
        
        # Log des données reçues pour debug
        logger.info(f"Données webhook: {json.dumps(webhook_data, indent=2, default=str)}")
        
        # Extraire les informations essentielles
        booking_id = webhook_data.get('id') or webhook_data.get('booking_id')
        event_type = webhook_data.get('type', 'unknown')
        
        if not booking_id:
            logger.error("Booking ID manquant")
            return jsonify({'status': 'error', 'message': 'Missing booking ID'}), 400
        
        # Extraire l'user_id depuis les données
        user_id = extract_user_id_from_webhook(webhook_data)
        if not user_id:
            logger.error("User ID manquant dans webhook")
            return jsonify({'status': 'error', 'message': 'Missing user ID'}), 400
        
        # Extraire le product_id
        product_id = (webhook_data.get('PRODUCT_ID') or 
                     webhook_data.get('formFields', {}).get('PRODUCT_ID') or 
                     'pack_clarte_fr')
        
        logger.info(f"Traitement: User {user_id}, Product {product_id}, Booking {booking_id}")
        
        # Traiter selon le type d'événement
        if event_type in ['booking.created', 'booking.confirmed', 'new_booking']:
            result = _handle_booking_created(user_id, product_id, booking_id, webhook_data)
        elif event_type in ['booking.cancelled', 'booking_cancelled']:
            result = _handle_booking_cancelled(user_id, product_id, booking_id, webhook_data)
        elif event_type in ['booking.rescheduled', 'booking_rescheduled']:
            result = _handle_booking_rescheduled(user_id, product_id, booking_id, webhook_data)
        else:
            # Traiter comme une création par défaut
            result = _handle_booking_created(user_id, product_id, booking_id, webhook_data)
        
        if result.get('success'):
            return jsonify({'status': 'success', 'data': result}), 200
        else:
            return jsonify({'status': 'error', 'data': result}), 400
            
    except Exception as e:
        logger.error(f"❌ Erreur webhook: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

def get_all_user_bookings(user_id):
    """Récupère TOUS les bookings d'un utilisateur (passés et futurs)."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT 
                b.id, b.booking_id, b.booking_date, b.end_date,
                b.duration_minutes, b.zoom_link, b.status, b.created_at,
                pc.product_id, pc.product_name, pc.emoji, pc.image_url
            FROM bookings b
            JOIN product_catalog pc ON b.product_id = pc.product_id
            WHERE b.user_id = %s 
              AND b.status IN ('confirmed', 'rescheduled')
            ORDER BY b.booking_date DESC
        ''', (user_id,))
        
        all_bookings = cursor.fetchall()
        
        # Séparer futurs et passés
        now = datetime.now()
        upcoming = []
        past = []
        
        for booking in all_bookings:
            booking_date = booking['booking_date']
            if isinstance(booking_date, datetime):
                booking_info = {
                    'id': booking['id'],
                    'booking_id': booking['booking_id'],
                    'booking_date': booking_date,
                    'product_name': booking['product_name'],
                    'product_id': booking['product_id'],
                    'image_url': booking['image_url'] or booking['emoji'] or '📦',
                    'formatted_date': format_date_fr(booking_date),
                    'status': booking['status']
                }
                
                if booking_date > now:
                    upcoming.append(booking_info)
                else:
                    past.append(booking_info)
        
        return {
            'upcoming': upcoming,
            'past': past,
            'total': len(all_bookings)
        }
        
    except Exception as e:
        logger.error(f"Erreur get_all_user_bookings: {str(e)}")
        return {'upcoming': [], 'past': [], 'total': 0}
    finally:
        cursor.close()



@dashboard_bp.route('/refresh-status')
@login_required
def refresh_status():
    """
    API pour polling - check si analyse prête ET email envoyé.
    """
    from utils import generate_request_id
    
    request_id = generate_request_id()
    user_id = current_user.id
    quiz_id = 'pack_clarte'
    
    try:
        cursor = current_app.mysql.connection.cursor(DictCursor)
        
        # ✅ Vérifier analyse active ET email déjà envoyé
        cursor.execute("""
            SELECT ru.result_id, ru.result_step_id
            FROM result_user ru
            JOIN analysis_notification_emails ane ON (
                ane.result_id = ru.result_id 
                AND ane.step_id = ru.result_step_id 
                AND ane.user_id = ru.user_id
            )
            WHERE ru.user_id = %s AND ru.quiz_id = %s AND ru.is_active = TRUE
            LIMIT 1
        """, (user_id, quiz_id))
        
        ready_and_notified = cursor.fetchone()
        cursor.close()
        
        is_ready = ready_and_notified is not None
        logger.info(f"[{request_id}] Status check - ready_and_notified={is_ready}")
        
        return jsonify({'ready': is_ready})
    
    except Exception as e:
        logger.error(f"[{request_id}] Status check error: {str(e)}")
        if 'cursor' in locals() and cursor:
            cursor.close()
        return jsonify({'ready': False}), 500

@dashboard_bp.route('/admin/stats/optin-rates', methods=['GET'])
@admin_required
def get_optin_rates():
    """Calcule les taux globaux d'opt-in et partners depuis le 9 octobre 2025"""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        start_date = '2025-10-09'
        
        # Total complété
        cursor.execute("""
            SELECT COUNT(DISTINCT qu.user_id) as total_completed
            FROM quiz_user qu
            WHERE qu.quiz_status = 'completed'
            AND qu.updated_at >= %s
        """, (start_date,))
        total_completed = cursor.fetchone()['total_completed']
        
        # ✅ CORRECTION : newsletter_subscription au lieu de optin
        cursor.execute("""
            SELECT COUNT(DISTINCT u.user_id) as optin_accepted
            FROM users u
            JOIN quiz_user qu ON u.user_id = qu.user_id
            WHERE u.newsletter_subscription = TRUE
            AND qu.quiz_status = 'completed'
            AND qu.updated_at >= %s
        """, (start_date,))
        optin_accepted = cursor.fetchone()['optin_accepted']
        
        # ✅ CORRECTION : partner_consent au lieu de partners
        cursor.execute("""
            SELECT COUNT(DISTINCT u.user_id) as partners_accepted
            FROM users u
            JOIN quiz_user qu ON u.user_id = qu.user_id
            WHERE u.partner_consent = TRUE
            AND qu.quiz_status = 'completed'
            AND qu.updated_at >= %s
        """, (start_date,))
        partners_accepted = cursor.fetchone()['partners_accepted']
        
        # Calcul des taux
        optin_rate = (optin_accepted / total_completed * 100) if total_completed > 0 else 0
        partners_rate = (partners_accepted / total_completed * 100) if total_completed > 0 else 0
        
        return jsonify({
            'success': True,
            'total_completed': total_completed,
            'optin': {
                'accepted': optin_accepted,
                'rate': round(optin_rate, 2)
            },
            'partners': {
                'accepted': partners_accepted,
                'rate': round(partners_rate, 2)
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur calcul optin rates: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        cursor.close()

# ──────────────────────────────────────────────────────────────────────
# HELPER: Detect Smart Contact status for current user
# ──────────────────────────────────────────────────────────────────────

def get_smart_contact_status(user_id):
    """
    Returns dict with Smart Contact info for this user.
    Utilise product_status (comme le reste du dashboard) au lieu de colonnes custom sur orders.
    """
    result = {
        'has_smart_contact': False,
        'quiz_completed': False,
        'order_status': None,
        'order_id': None,
        'product_id': None
    }

    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)

        # Chercher une commande Smart Contact payée via order_product
        cursor.execute("""
            SELECT o.order_id, op.product_id, ps.status as order_status
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            LEFT JOIN product_status ps ON ps.user_id = o.user_id AND ps.product_id = op.product_id
            WHERE o.user_id = %s
              AND op.product_id LIKE '%%smart_contact%%'
              AND o.status = 'paid'
            ORDER BY o.created_at DESC
            LIMIT 1
        """, (user_id,))

        order = cursor.fetchone()
        cursor.close()

        if order:
            result['has_smart_contact'] = True
            result['order_id'] = order['order_id']
            result['product_id'] = order['product_id']
            result['order_status'] = order.get('order_status') or 'achat_confirmé'
            # Quiz est complété si le statut est passé au-delà de achat_confirmé
            result['quiz_completed'] = order.get('order_status') in ('analyse_en_cours', 'livrable_dispo', 'post_livraison')

    except Exception as e:
        logger.error(f"[SC] Error getting smart contact status: {e}")

    return result


def get_bilan_express_status(user_id):
    """Retourne le statut Bilan Carrière Express pour cet utilisateur."""
    result = {'has_bilan': False, 'order_id': None, 'product_id': None}
    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        cursor.execute("""
            SELECT o.order_id, op.product_id
            FROM orders o
            JOIN order_product op ON o.order_id = op.order_id
            WHERE o.user_id = %s
              AND op.product_id LIKE '%bilan_carriere_express%'
              AND o.status = 'paid'
            ORDER BY o.created_at DESC
            LIMIT 1
        """, (user_id,))
        order = cursor.fetchone()
        cursor.close()
        if order:
            result['has_bilan'] = True
            result['order_id'] = order['order_id']
            result['product_id'] = order['product_id']
    except Exception as e:
        logger.error(f"Erreur get_bilan_express_status: {e}")
    return result

# ──────────────────────────────────────────────────────────────────────
# HELPER: Check if user has an existing diagnostic (pack_clarte etc.)
# ──────────────────────────────────────────────────────────────────────

def get_diagnostic_info(user_id):
    """Returns dict with existing diagnostic info."""
    result = {'has_diagnostic': False, 'diagnostic_url': None}

    try:
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        cursor.execute("""
            SELECT ru.result_id, ru.result_step_id
            FROM result_user ru
            WHERE ru.user_id = %s AND ru.is_active = TRUE
            ORDER BY ru.created_at DESC
            LIMIT 1
        """, (user_id,))

        diag = cursor.fetchone()
        cursor.close()

        if diag:
            result['has_diagnostic'] = True
            result['diagnostic_url'] = f"/quiz/pack_clarte/analysis/{diag['result_id']}/{diag['result_step_id']}"

    except Exception as e:
        logger.error(f"[SC] Error getting diagnostic info: {e}")

    return result

@dashboard_bp.route('/smart-contact/onboarding')
@login_required
def smart_contact_onboarding():
    """Full-page quiz for Smart Contact purchasers."""
    user_id = current_user.id
    user_email = current_user.email


    # Verify user actually purchased Smart Contact
    sc_status = get_smart_contact_status(user_id)

    if not sc_status['has_smart_contact']:
        flash("Vous n'avez pas de commande Smart Contact.", "warning")
        return redirect(url_for('dashboard.index'))

    # If quiz already completed, go back to dashboard
    if sc_status['quiz_completed']:
        return redirect(url_for('dashboard.index'))

    # Check for existing diagnostic
    diag_info = get_diagnostic_info(user_id)

    return render_template(
        'pages/dashboard/smart_contact_onboarding.html',
        user_email=user_email,
        has_diagnostic=diag_info['has_diagnostic'],
        diagnostic_url=diag_info['diagnostic_url'],
        order_status=sc_status['order_status']
    )


# ──────────────────────────────────────────────────────────────────────
# ROUTE: Complete Smart Contact quiz → update order status
# ──────────────────────────────────────────────────────────────────────

@dashboard_bp.route('/smart-contact/complete', methods=['POST'])
@login_required
def smart_contact_complete():
    """
    Called when user completes the Smart Contact questionnaire.
    Updates product_status to 'analyse_en_cours'.
    """
    user_id = current_user.id

    try:
        sc_status = get_smart_contact_status(user_id)

        if not sc_status['has_smart_contact']:
            return jsonify({'success': False, 'error': 'No Smart Contact order found'}), 404

        if sc_status['quiz_completed']:
            return jsonify({'success': True, 'message': 'Already completed'}), 200

        # Utiliser update_user_product_status comme le reste du dashboard
        result = update_user_product_status(
            user_id=user_id,
            product_id=sc_status['product_id'],
            status='analyse_en_cours',
            admin_note='Quiz Smart Contact complété',
            order_id=sc_status['order_id']
        )

        if result:
            logger.info(f"[SC] Quiz completed for user {user_id}, order {sc_status['order_id']}")
            return jsonify({
                'success': True,
                'message': 'Quiz completed',
                'new_status': 'analyse_en_cours',
                'redirect': url_for('dashboard.index')
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Update failed'}), 500

    except Exception as e:
        logger.error(f"[SC] Error completing quiz: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500

# ──────────────────────────────────────────────────────────────────────
# ROUTE: Get Smart Contact status (API, for JS polling if needed)
# ──────────────────────────────────────────────────────────────────────

@dashboard_bp.route('/smart-contact/status')
@login_required
def smart_contact_status_api():
    """Returns current Smart Contact status as JSON."""
    user_id = current_user.id

    sc_status = get_smart_contact_status(user_id)

    return jsonify({
        'has_smart_contact': sc_status['has_smart_contact'],
        'quiz_completed': sc_status['quiz_completed'],
        'order_status': sc_status['order_status']
    })
# ──────────────────────────────────────────────────────────────────────
# ROUTE: Save phone number for Smart Contact
# ──────────────────────────────────────────────────────────────────────

@dashboard_bp.route('/smart-contact/save-phone', methods=['POST'])
def smart_contact_save_phone():
    """
    Sauvegarde le numéro de téléphone après achat Smart Contact ou Bilan Carrière Express.
    Supporte les users connectés ET les guests (via order_id).
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Données manquantes'}), 400

        phone = data.get('phone', '').strip()
        order_id = data.get('order_id')

        if not phone or len(phone) < 8:
            return jsonify({'success': False, 'message': 'Numéro de téléphone invalide'}), 400

        # Nettoyer le numéro
        phone_clean = re.sub(r'[^\d\+\s\-\.]', '', phone).strip()

        # ── Résolution du user : connecté ou guest via order_id ──
        if current_user.is_authenticated:
            user_id = current_user.id
            user_email = current_user.email
        else:
            if not order_id:
                return jsonify({'success': False, 'message': 'Non authentifié'}), 401
            cursor = current_app.mysql.connection.cursor(DictCursor)
            cursor.execute("""
                SELECT o.user_id, u.email
                FROM orders o
                JOIN users u ON o.user_id = u.user_id
                WHERE o.order_id = %s AND o.user_id IS NOT NULL
            """, (order_id,))
            row = cursor.fetchone()
            cursor.close()
            if not row:
                return jsonify({'success': False, 'message': 'Commande introuvable'}), 404
            user_id = row['user_id']
            user_email = row['email']

        # ── Sauvegarder le téléphone ──
        cursor = current_app.mysql.connection.cursor(DictCursor)
        cursor.execute("""
            UPDATE users
            SET phone_number = %s,
                updated_at = NOW()
            WHERE user_id = %s
        """, (phone_clean, user_id))
        current_app.mysql.connection.commit()
        cursor.close()

        logger.info(f"[SC] Téléphone enregistré pour user {user_id}: {phone_clean}")

        # ── Mettre à jour le statut produit si Smart Contact ──
        sc_status = get_smart_contact_status(user_id)
        if sc_status['has_smart_contact']:
            result = update_user_product_status(
                user_id=user_id,
                product_id=sc_status['product_id'],
                status='analyse_en_cours',
                admin_note=f'Téléphone renseigné: {phone_clean}',
                order_id=sc_status['order_id']
            )
            if not result:
                logger.warning(f"[SC] Impossible de mettre à jour le statut pour user {user_id}")

        # ── Notifier Slack ──
        try:
            from services import slack_service, SLACK_AVAILABLE
            if SLACK_AVAILABLE and slack_service:
                slack_service.send_notification(
                    message=(
                        f"📞 *Nouveau rappel à planifier*\n"
                        f"• Utilisateur : {user_email}\n"
                        f"• Téléphone : {phone_clean}\n"
                        f"• Commande : #{order_id or sc_status.get('order_id', 'N/A')}"
                    ),
                    channel='monitoring'
                )
        except Exception as e:
            logger.warning(f"[SC] Erreur Slack: {e}")

        return jsonify({'success': True, 'message': 'Numéro enregistré'}), 200

    except Exception as e:
        logger.error(f"[SC] Erreur save_phone: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Une erreur est survenue'}), 500