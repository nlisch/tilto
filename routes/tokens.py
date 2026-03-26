# token.py
import logging
from flask import Blueprint, jsonify, request, render_template, current_app, url_for, redirect, session, flash, g
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import uuid
from flask_babel import _
import stripe
from MySQLdb.cursors import DictCursor
import json
from typing import Dict, List, Optional, Tuple
import os
import re

from extensions import csrf, limiter, mail
from decorators import admin_required
from .coupons import CouponManager
from services import send_purchase_confirmation_email
from models import User

token_bp = Blueprint('tokens', __name__)
logger = logging.getLogger(__name__)

def generate_order_number():
    """Génère un numéro de commande unique."""
    prefix = "ORD"
    random_part = uuid.uuid4().hex.upper()[:9]
    return f"{prefix}{random_part}"

def init_stripe():
    """Initialise la configuration Stripe."""
    logger.debug("🔑 [TOKEN] Initialisation Stripe")
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')

@token_bp.before_app_first_request
def initialize():
    init_stripe()

@token_bp.route('/shop', methods=['GET'])
def shop():
    """Affiche la boutique avec les produits disponibles."""
    # Récupérer le paramètre "pack" de l'URL
    pack_type = request.args.get('pack')
    logger.info(f"Accès à la boutique - pack_type: {pack_type}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    try:
        # Log des informations utilisateur
        logger.info(f"Utilisateur: {current_user.id if current_user.is_authenticated else 'Non authentifié'}, Pays: {current_user.country_code.upper() if current_user.is_authenticated and hasattr(current_user, 'country_code') else 'N/A'}")
        
        sql_query = """
            SELECT DISTINCT
                pc.product_id,
                pc.product_name,
                pc.unit_amount,
                pc.emoji,
                pc.subtitle,
                pc.button_text,
                pc.is_featured,
                GROUP_CONCAT(DISTINCT qc.quiz_id) as quiz_ids,
                GROUP_CONCAT(DISTINCT qc.quiz_type) as quiz_types
            FROM product_catalog pc
            JOIN product_items pi ON pc.product_id = pi.product_id
            JOIN product_catalog_items pci ON pi.item_id = pci.item_id
            JOIN item_quiz iq ON pci.item_id = iq.item_id
            JOIN quiz_catalog qc ON iq.quiz_id = qc.quiz_id
            WHERE pc.is_active = TRUE
            AND pc.country_code = %s
            AND pi.is_active = TRUE  
            AND pci.is_active = TRUE 
        """

        # Ajouter un filtre pour le Pack Clarté si demandé
        params = [current_user.country_code.upper() if current_user.is_authenticated and hasattr(current_user, 'country_code') else 'FR']
        if pack_type == 'clarte':
            sql_query += " AND pc.product_id = %s"
            params.append('pack_clarte_fr')
            logger.info(f"Filtrage pour Pack Clarté activé")

        # Ajoutez le GROUP BY à la fin de la requête
        sql_query += " GROUP BY pc.product_id, pc.product_name, pc.unit_amount, pc.emoji, pc.subtitle, pc.button_text, pc.is_featured"

        # Log de la requête SQL
        logger.debug(f"SQL Query: {sql_query}")
        logger.debug(f"SQL Params: {params}")

        # Exécuter la requête avec les paramètres
        cursor.execute(sql_query, params)
        
        # Récupérer les résultats de la requête
        products_db = cursor.fetchall()
        logger.info(f"Nombre de produits trouvés dans la DB: {len(products_db) if products_db else 0}")
        
        if not products_db:
            logger.warning("Aucun produit trouvé dans la base de données")
        else:
            # Log détaillé des produits trouvés
            for i, p in enumerate(products_db):
                logger.debug(f"Produit {i+1}: ID={p['product_id']}, Nom={p['product_name']}, Prix={p['unit_amount']}")
        
        # Récupérer les IDs Stripe depuis la configuration
        is_production = bool(os.getenv('GOOGLE_CLOUD_PROJECT'))
        env = 'prod' if is_production else 'dev'
        stripe_products = current_app.config.get('STRIPE_PRODUCTS', {})
        
        logger.debug(f"Environment: {env}")
        logger.debug(f"Stripe Products config: {stripe_products}")
        
        # 2. Récupérer les fonctionnalités pour chaque produit
        product_ids = [p['product_id'] for p in products_db]
        if product_ids:
            # Utilisez IN pour récupérer les fonctionnalités de tous les produits en une seule requête
            placeholders = ', '.join(['%s'] * len(product_ids))
            cursor.execute(f"""
                SELECT 
                    product_id,
                    feature_order,
                    feature_icon,
                    feature_text
                FROM product_features
                WHERE product_id IN ({placeholders})
                AND is_active = TRUE
                ORDER BY product_id, feature_order
            """, product_ids)
            
            # Créer un dictionnaire des fonctionnalités par product_id
            features_by_product = {}
            for feature in cursor.fetchall():
                if feature['product_id'] not in features_by_product:
                    features_by_product[feature['product_id']] = []
                
                features_by_product[feature['product_id']].append({
                    'icon': feature['feature_icon'],
                    'text': feature['feature_text']
                })
            
            logger.debug(f"Fonctionnalités récupérées pour {len(features_by_product)} produits")
        else:
            features_by_product = {}
            logger.debug("Aucun produit trouvé, pas de fonctionnalités à récupérer")
            
        # 3. Construire la liste finale des produits avec leurs fonctionnalités
        products = []  # Définir la variable products ici
        for p in products_db:
            # Vérifier si on a une configuration spécifique pour ce produit
            stripe_config = stripe_products.get(p['product_id'], {}).get(env, {})
            stripe_price_id = stripe_config.get('stripe_price_id')
            
            # Ne pas afficher les produits sans stripe_price_id valide
            if not stripe_price_id:
                logger.warning(f"Produit {p['product_id']} sans stripe_price_id valide, non affiché")
                continue
                
            # Créer le produit de base
            product_data = {
                'product_id': p['product_id'],
                'product_name': p['product_name'],
                'price_id': stripe_price_id,
                'price': round(p['unit_amount'] / 100, 2),
                'emoji': p.get('emoji', '🧭'),
                'subtitle': p.get('subtitle', _('1h pour transformer vos questions en actions')),
                'button_text': p.get('button_text', _('Réserver ma session maintenant')),
                'is_featured': p.get('is_featured', False),
                'quiz_ids': p['quiz_ids'].split(',') if p['quiz_ids'] else [],
                'quiz_types': p['quiz_types'].split(',') if p['quiz_types'] else []
            }
            
            # Ajouter les fonctionnalités personnalisées si disponibles
            if p['product_id'] in features_by_product:
                product_data['features'] = features_by_product[p['product_id']]
                logger.debug(f"Ajout de {len(product_data['features'])} fonctionnalités pour {p['product_id']}")
            
            products.append(product_data)
            logger.debug(f"Produit ajouté à l'affichage: {p['product_id']}, Prix: {product_data['price']}€")
            
        logger.info(f"Nombre total de produits à afficher: {len(products)}")
            
        # Si c'est le Pack Clarté, personnaliser le titre
        page_title = _('Votre carrière mérite ce moment')
        page_subtitle = _('Choisissez l\'option qui vous convient et commencez à clarifier votre chemin professionnel dès aujourd\'hui')
        
        if pack_type == 'clarte':
            page_title = _('Le Pack Clarté')
            page_subtitle = _('Une vraie conversation pour scanner ta vie pro, lever les freins invisibles, et tracer un cap clair')
            logger.debug(f"Titres personnalisés pour Pack Clarté appliqués")
        
        # Passer les variables au template
        logger.info(f"Rendu du template avec {len(products)} produits")
        return render_template(
            'order/shop.html',
            products=products,
            stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'],
            page_title=page_title,
            page_subtitle=page_subtitle,
            is_pack_clarte=(pack_type == 'clarte')
        )
    except Exception as e:
        logger.error(f"Error fetching products: {e}", exc_info=True)
        return render_template('order/shop.html', 
            products=[], 
            stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'],
            page_title=_('Votre carrière mérite ce moment'),
            page_subtitle=_('Choisissez l\'option qui vous convient et commencez à clarifier votre chemin professionnel dès aujourd\'hui')
        )
    finally:
        cursor.close()

@token_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    data = request.get_json()
    product_id = data.get('product_id')
    coupon_code = data.get('coupon_code', '').strip()

    if not product_id:
        return jsonify({'error': _('Product ID requis')}), 400

    session['checkout_product_id'] = product_id
    session['checkout_coupon_code'] = coupon_code

    if not current_user.is_authenticated:
        return jsonify({
                'redirect': True,
                'url': url_for('auth.checkout_auth', product_id=product_id)
                })

    try:
        stripe_session = build_stripe_checkout_session(current_user, product_id)
        return jsonify({
            'sessionId': stripe_session.id,
            'order_number': stripe_session.metadata['order_number']
        }), 200

    except Exception as e:
        logger.error(f"Erreur création checkout session: {e}", exc_info=True)
        return jsonify({'error': _('Une erreur est survenue lors de la création de la session de paiement')}), 500


@token_bp.route('/success')
def success():
    """Page de succès après un paiement réussi"""
    session_id = request.args.get('session_id')
    logger = logging.getLogger('token_bp')
    
    if not session_id:
        logger.error("Session ID manquant dans la requête")
        return render_template('order/error.html', error=_("Session de paiement invalide"))
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier d'abord le statut dans notre base
        cursor.execute("""
            SELECT status
            FROM orders
            WHERE stripe_session_id = %s
        """, (session_id,))
        
        order_status = cursor.fetchone()
        
        # Si la commande n'existe pas ou n'est pas en statut 'paid'
        if not order_status or order_status['status'] != 'paid':
            # Vérifier Stripe avant d'abandonner — webhook peut-être pas encore arrivé
            stripe_check = stripe.checkout.Session.retrieve(session_id)
            if stripe_check.payment_status == 'paid':
                logger.info(f"Commande {session_id} payée sur Stripe mais webhook pas encore arrivé — polling")
                return render_template('order/waiting.html', session_id=session_id)
            logger.warning(f"Commande {session_id} non payée, status: {order_status['status'] if order_status else 'non trouvé'}")
            return redirect(url_for('tokens.payment_failed', 
                                error="payment_incomplete",
                                session_id=session_id))
        
        # Ensuite, vérifier avec Stripe pour double confirmation
        logger.info(f"Récupération de la session Stripe: {session_id}")
        stripe_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['total_details.breakdown']
        )
        
        if stripe_session.payment_status != 'paid':
            logger.warning(f"Session {session_id} non payée dans Stripe, status: {stripe_session.payment_status}")
            return redirect(url_for('tokens.payment_failed', 
                                error="payment_incomplete",
                                session_id=session_id))
                                
        logger.info(f"Récupération de la session Stripe: {session_id}")
        stripe_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=['total_details.breakdown']
        )
        
        if stripe_session.payment_status != 'paid':
            logger.warning(f"Session {session_id} non payée, status: {stripe_session.payment_status}")
            return redirect(url_for('tokens.payment_failed', 
                              error="payment_incomplete",
                              session_id=session_id))
        
        logger.info(f"Récupération des informations de commande pour session: {session_id}")
        cursor.execute("""
        SELECT 
            o.order_number,
            o.order_id,
            pc.product_id,
            pc.product_name AS quiz_name,
            t.token_code,
            t.expiration_date,
            o.base_amount,
            o.vat_amount,
            o.order_amount,
            o.origin_order_amount,
            o.currency,
            o.discount_code,
            o.discount_amount,
            o.status,
            c.discount_type,
            c.discount_value,
            c.coupon_code,
            o.user_id
        FROM orders o
        LEFT JOIN order_product op ON o.order_id = op.order_id
        LEFT JOIN product_catalog pc ON op.product_id = pc.product_id
        LEFT JOIN tokens t ON o.order_id = t.order_id
        LEFT JOIN coupons c ON o.discount_code = c.coupon_code
        WHERE o.stripe_session_id = %s
        """, (session_id,))
        
        order = cursor.fetchone()
        
        if not order:
            logger.error(f"Commande non trouvée pour session: {session_id}")
            return redirect(url_for('tokens.payment_failed', 
                              error="order_not_found",
                              session_id=session_id))

        logger.debug(f"Données de commande brutes: {order}")
        
        # Initialiser order_data à partir de order
        try:
            order_data = {
                'order_number': order['order_number'],
                'order_id': order['order_id'],
                'product_id': order['product_id'],
                'quiz_name': order['quiz_name'],
                'token_code': order['token_code'],
                'expiration_date': None,
                'base_amount': float(order['base_amount'])/100 if order['base_amount'] else 0,
                'vat_amount': float(order['vat_amount'])/100 if order['vat_amount'] else 0,
                'order_amount': float(order['order_amount'])/100 if order['order_amount'] else 0,
                'origin_order_amount': float(order['origin_order_amount'])/100 if order['origin_order_amount'] else 0,
                'currency': order['currency'],
                'discount_code': None,
                'discount_amount': 0,
                'status': order['status']
            }

            # Gestion de la date d'expiration
            if order['expiration_date']:
                try:
                    order_data['expiration_date'] = order['expiration_date'].strftime("%d/%m/%Y %H:%M")
                except AttributeError as e:
                    logger.warning(f"Erreur formatage date expiration: {e}")
                    order_data['expiration_date'] = None

            # Gestion des réductions avec type
            if order['discount_code']:
                order_data['discount_code'] = str(order['discount_code'])
                order_data['discount_type'] = order['discount_type']  # 'percentage' ou 'fixed'
                
                if order['discount_amount']:
                    try:
                        discount = float(order['discount_amount'])
                        order_data['discount_amount'] = f"{discount/100:.2f}"
                        if order['discount_type'] == 'percentage':
                            order_data['discount_value'] = float(order['discount_value'])
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Erreur conversion montant réduction: {e}")
                        order_data['discount_amount'] = "0.00"
        except (ValueError, TypeError) as ve:
            logger.error(f"Erreur lors de la conversion des données: {str(ve)}", exc_info=True)
            raise
            
        # NOUVEAU: Initialisation du statut pour le Pack Clarté (ou autre produit à suivi)
        # Vérifier si c'est un produit qui nécessite un suivi post-achat
        product_name = order['quiz_name']
        product_id = order['product_id']
        user_id = order['user_id']
        
        # Les produits qui nécessitent un suivi post-achat
        tracked_products = ['Pack Clarté', 'Pack Clarte', 'Transition Pro', 'Coaching']
        
        needs_tracking = any(tracked_name in product_name for tracked_name in tracked_products)
        
        if needs_tracking and user_id:
            try:
                # Importer la fonction du blueprint dashboard
                from routes.dashboard import get_user_product_status, update_user_product_status
                
                # Vérifier si le statut existe déjà
                product_status = get_user_product_status(user_id, product_id)
                
                # Si pas de statut, initialiser à "achat_confirmé"
                if not product_status:
                    update_user_product_status(user_id, product_id, "achat_confirmé")
                    logger.info(f"Statut post-achat initialisé pour l'utilisateur {user_id}, produit {product_id}")
            except Exception as tracking_error:
                logger.error(f"Erreur lors de l'initialisation du statut post-achat: {str(tracking_error)}", exc_info=True)
                # On continue malgré l'erreur pour ne pas bloquer la confirmation de commande

        logger.info(f"Données de commande préparées avec succès: {order_data}")

        # Construire l'URL d'analyse si disponible
        analysis_url = None
        if order['user_id']:
            try:
                cursor.execute("""
                    SELECT result_id, result_step_id
                    FROM result_user
                    WHERE user_id = %s AND quiz_id = 'pack_clarte' AND is_active = TRUE
                    ORDER BY created_at DESC LIMIT 1
                """, (order['user_id'],))
                
                analysis = cursor.fetchone()
                if analysis:
                    analysis_url = url_for('quiz_analysis.view_analysis', 
                                        quiz_id='pack_clarte', 
                                        result_id=analysis['result_id'], 
                                        step_id=analysis['result_step_id'])
            except Exception as e:
                logger.warning(f"Impossible de récupérer analysis_url: {e}")

        is_smart_contact = 'smart_contact' in (order_data.get('product_id') or '')
        is_bilan = 'bilan_carriere_express' in (order_data.get('product_id') or '')
        return render_template('order/success.html', order=order_data, analysis_url=analysis_url, is_smart_contact=is_smart_contact, is_bilan=is_bilan, bilan_slug=session.get('bilan_flash_slug'), bilan_meta=session.get('bilan_flash_meta', {}))

    except stripe.error.StripeError as e:
        logger.error(f"Erreur Stripe: {str(e)}")
        return redirect(url_for('tokens.payment_failed', 
                          error="stripe_error",
                          session_id=session_id))
    
    except Exception as e:
        logger.error(f"Erreur interne détaillée: {str(e)}", exc_info=True)
        return redirect(url_for('tokens.payment_failed', 
                          error="internal_error",
                          session_id=session_id))
    
    finally:
        cursor.close()


@token_bp.route('/payment-failed')
def payment_failed():
    """Gestion des échecs de paiement."""
    error_code = request.args.get('error', 'unknown')
    session_id = request.args.get('session_id')
    
    # ✅ AJOUT : Récupérer le product_id depuis la session Stripe
    product_id = None
    coupon_code = None
    
    if session_id:
        try:
            stripe_session = stripe.checkout.Session.retrieve(session_id)
            if stripe_session.metadata:
                order_number = stripe_session.metadata.get('order_number')
                if order_number:
                    mysql = current_app.mysql
                    cursor = mysql.connection.cursor(DictCursor)
                    try:
                        cursor.execute("""
                            SELECT op.product_id, o.discount_code
                            FROM orders o
                            JOIN order_product op ON o.order_id = op.order_id
                            WHERE o.order_number = %s
                            LIMIT 1
                        """, (order_number,))
                        result = cursor.fetchone()
                        if result:
                            product_id = result['product_id']
                            coupon_code = result['discount_code']
                    finally:
                        cursor.close()
        except Exception as e:
            logger.warning(f"Impossible de récupérer le product_id: {e}")

    error_messages = {
        'payment_incomplete': {
            'message': _("Le paiement n'a pas été complété."),
            'action': _("Vous pouvez réessayer le paiement ou nous contacter.")
        },
        'order_not_found': {
            'message': _("La commande est introuvable."),
            'action': _("Veuillez réessayer votre achat.")
        },
        'invalid_token': {
            'message': _("Le token est invalide ou déjà utilisé."),
            'action': _("Contactez le support si nécessaire.")
        },
        'invalid_status': {
            'message': _("Statut de commande invalide."),
            'action': _("Veuillez vérifier votre tableau de bord.")
        },
        'stripe_error': {
            'message': _("Erreur avec le service de paiement."),
            'action': _("Veuillez réessayer dans quelques instants.")
        },
        'internal_error': {
            'message': _("Une erreur interne est survenue."),
            'action': _("Notre équipe technique a été notifiée.")
        },
        'unknown': {
            'message': _("Une erreur inconnue est survenue."),
            'action': _("Veuillez réessayer ou contacter le support.")
        }
    }
    
    error_info = error_messages.get(error_code, error_messages['unknown'])
    
    logger.error(f"Échec paiement - Code: {error_code}, Session: {session_id}")
    
    return render_template(
        'order/error.html',
        error=error_info['message'],
        action=error_info['action'],
        support_email='contact@tilto.ai',
        product_id=product_id,
        coupon_code=coupon_code
    )

@token_bp.route('/cancel')
def cancel():
    """Page d'annulation du paiement."""
    session_id = request.args.get('session_id')
    
    # Récupérer le product_id depuis la session Stripe
    product_id = None
    coupon_code = None
    
    if session_id:
        try:
            stripe_session = stripe.checkout.Session.retrieve(session_id)
            if stripe_session.metadata:
                order_number = stripe_session.metadata.get('order_number')
                if order_number:
                    mysql = current_app.mysql
                    cursor = mysql.connection.cursor(DictCursor)
                    try:
                        cursor.execute("""
                            SELECT op.product_id, o.discount_code
                            FROM orders o
                            JOIN order_product op ON o.order_id = op.order_id
                            WHERE o.order_number = %s
                            LIMIT 1
                        """, (order_number,))
                        result = cursor.fetchone()
                        if result:
                            product_id = result['product_id']
                            coupon_code = result['discount_code']
                    finally:
                        cursor.close()
        except Exception as e:
            logger.warning(f"Impossible de récupérer le product_id: {e}")
    
    return render_template(
        'order/cancel.html',
        support_email='contact@tilto.ai',
        product_id=product_id,
        coupon_code=coupon_code
    )

@token_bp.route('/stripe-webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    """Gère les webhooks Stripe de manière robuste et idempotente."""
    logger = logging.getLogger('token_bp')
    
    # 1. Validation initiale du webhook
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

    if not webhook_secret:
        logger.error("❌ STRIPE_WEBHOOK_SECRET manquant")
        return jsonify({'error': 'Configuration error'}), 500

    if not sig_header:
        logger.error("❌ Stripe-Signature manquante")
        return jsonify({'error': 'No signature provided'}), 401

    try:
        # 2. Vérification de la signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        
        # 3. Gestion idempotente des événements
        event_id = event.id
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)

        try:
            # Vérifier si l'événement a déjà été traité
            cursor.execute("""
                SELECT id, status FROM stripe_events 
                WHERE stripe_event_id = %s
                FOR UPDATE
            """, (event_id,))
            
            existing_event = cursor.fetchone()
            
            if existing_event:
                logger.info(f"📝 Événement {event_id} déjà traité, status: {existing_event['status']}")
                return jsonify({'status': 'already processed'}), 200

            # Enregistrer l'événement avant traitement
            cursor.execute("""
                INSERT INTO stripe_events (stripe_event_id, event_type, status, created_at)
                VALUES (%s, %s, %s, NOW())
            """, (event_id, event.type, 'processing'))
            
            mysql.connection.commit()

            # 4. Traitement spécifique selon le type d'événement
            if event.type == 'checkout.session.completed':
                session = event.data.object
                
                # Vérifier si le paiement est réellement réussi
                if session.payment_status == 'paid':
                    try:
                        handle_successful_payment(session)
                        
                        # Marquer l'événement comme traité avec succès
                        cursor.execute("""
                            UPDATE stripe_events 
                            SET status = 'completed',
                                processed_at = NOW(),
                                error = NULL
                            WHERE stripe_event_id = %s
                        """, (event_id,))
                        
                        mysql.connection.commit()
                        logger.info(f"✅ Paiement traité avec succès pour la session {session.id}")
                        
                    except Exception as process_error:
                        # En cas d'erreur, enregistrer l'erreur mais ne pas lever d'exception
                        error_msg = str(process_error)
                        cursor.execute("""
                            UPDATE stripe_events 
                            SET status = 'error',
                                processed_at = NOW(),
                                error = %s,
                                retry_count = retry_count + 1
                            WHERE stripe_event_id = %s
                        """, (error_msg[:255], event_id))
                        
                        mysql.connection.commit()
                        logger.error(f"❌ Erreur lors du traitement: {error_msg}", exc_info=True)
                        # Retourner 200 pour éviter les retries automatiques de Stripe
                        return jsonify({'status': 'error', 'message': 'Processing error logged'}), 200
                
                else:
                    logger.warning(f"⚠️ Session {session.id} non payée, status: {session.payment_status}")
            
            return jsonify({'status': 'success', 'type': event.type}), 200

        except Exception as db_error:
            mysql.connection.rollback()
            logger.error(f"❌ Erreur base de données: {str(db_error)}", exc_info=True)
            return jsonify({'error': 'Database error'}), 500

        finally:
            cursor.close()

    except ValueError as e:
        logger.error(f"❌ Erreur de payload: {str(e)}")
        return jsonify({'error': 'Invalid payload'}), 400
        
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"❌ Signature invalide: {str(e)}")
        return jsonify({'error': 'Invalid signature'}), 401
        
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {str(e)}", exc_info=True)
        return jsonify({'error': 'Unexpected error'}), 500


from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
import json
import time

def handle_successful_payment(session):
    """
    Gère un paiement réussi en créant un token et en déclenchant la génération.
    ✅ NOUVEAU : Déclenche automatiquement Cloud Tasks
    """
    logger = logging.getLogger('token_bp')
    
    try:
        stripe_session = stripe.checkout.Session.retrieve(
            session.id,
            expand=['total_details.breakdown']
        )
        
        discount_code = None
        if (hasattr(stripe_session, 'total_details') and 
            hasattr(stripe_session.total_details, 'breakdown') and 
            stripe_session.total_details.breakdown.get('discounts')):
            
            discounts = stripe_session.total_details.breakdown['discounts']
            if discounts and discounts[0].get('discount', {}).get('coupon', {}).get('name'):
                discount_code = discounts[0]['discount']['coupon']['name']
        
        if stripe_session.payment_status != 'paid':
            logger.warning(f"Payment status not paid: {stripe_session.payment_status}")
            return

        order_number = stripe_session.metadata.get('order_number')
        quiz_id = stripe_session.metadata.get('quiz_id')
        
        logger.info(f"Traitement paiement - Order: {order_number}, Quiz: {quiz_id}, Discount: {discount_code}")
        
        if not order_number or not quiz_id:
            logger.error("Métadonnées manquantes")
            return

        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)

        try:
            mysql.connection.begin()

            # ── GUEST CHECKOUT : résoudre le user depuis l'email Stripe ─────
            cursor.execute("""
                SELECT order_id, user_id FROM orders
                WHERE order_number = %s FOR UPDATE
            """, (order_number,))
            order_row = cursor.fetchone()
            if not order_row:
                logger.error(f"Order non trouvé: {order_number}")
                return

            if order_row['user_id'] is None:
                stripe_email = (stripe_session.customer_details.email
                                if stripe_session.customer_details else None)
                if not stripe_email:
                    logger.error(f"Pas d'email Stripe pour order {order_number}")
                    try:
                        from services import slack_service, SLACK_AVAILABLE
                        if SLACK_AVAILABLE and slack_service:
                            slack_service.send_message(
                                channel='#alerts-paiement',
                                text=f"🚨 PAIEMENT SANS EMAIL\n"
                                     f"• Order: {order_number}\n"
                                     f"• Session Stripe: {session.id}\n"
                                     f"• Action: récupérer l'email dans le dashboard Stripe et traiter manuellement"
                            )
                    except Exception as slack_err:
                        logger.error(f"Slack error: {slack_err}")
                    return
                status, resolved_user = get_or_create_pending_user(stripe_email)
                if status in ('error',) or (status == 'existing' and resolved_user is None):
                    cursor.execute("SELECT user_id FROM users WHERE email = %s", (stripe_email,))
                    existing_row = cursor.fetchone()
                    if not existing_row:
                        logger.error(f"Impossible de résoudre le user pour {stripe_email}")
                        return
                    resolved_user_id = existing_row['user_id']
                else:
                    resolved_user_id = resolved_user.id
                cursor.execute("UPDATE orders SET user_id = %s WHERE order_id = %s",
                               (resolved_user_id, order_row['order_id']))
                logger.info(f"✅ Guest order rattaché à user_id={resolved_user_id}")
            # ── FIN GUEST CHECKOUT ────────────────────────────────────────────

            # Récupérer l'ordre complet avec les infos utilisateur
            cursor.execute("""
                SELECT o.order_id, o.user_id, u.country_code, o.discount_code,
                       o.origin_order_amount, o.base_amount, o.vat_amount,
                       u.email as user_email, u.username, u.firstname
                FROM orders o
                JOIN users u ON o.user_id = u.user_id
                WHERE o.order_number = %s
                FOR UPDATE
            """, (order_number,))
            
            order_info = cursor.fetchone()
            if not order_info:
                logger.error(f"Order non trouvé après résolution guest: {order_number}")
                return

            # Récupérer les détails produit et item
            cursor.execute("""
                SELECT 
                    op.product_id,
                    op.quantity,
                    op.unit_price,
                    op.discount_amount,
                    oi.item_id,
                    pc.product_name
                FROM order_product op
                JOIN order_item oi ON op.order_id = oi.order_id
                JOIN product_catalog pc ON op.product_id = pc.product_id
                WHERE op.order_id = %s
                LIMIT 1
            """, (order_info['order_id'],))
            
            product_info = cursor.fetchone()
            if not product_info:
                logger.error(f"Produit non trouvé pour order: {order_info['order_id']}")
                return

            # Calculer les montants de réduction
            discount_amount = (stripe_session.total_details.amount_discount 
                            if hasattr(stripe_session, 'total_details') else 0)
            final_amount = max(0, order_info['origin_order_amount'] - discount_amount)

            # Mettre à jour l'ordre
            cursor.execute("""
                UPDATE orders 
                SET status = 'paid',
                    discount_code = %s,
                    discount_amount = %s,
                    order_amount = %s,
                    updated_at = NOW()
                WHERE order_id = %s
            """, (discount_code, discount_amount, final_amount, order_info['order_id']))

            cursor.execute("""
                UPDATE order_product 
                SET discount_amount = %s,
                    product_amount = %s
                WHERE order_id = %s
            """, (discount_amount, final_amount, order_info['order_id']))

            # Gérer le coupon si présent
            discount_type = None
            discount_value = None
            
            if discount_code:
                cursor.execute("""
                    SELECT stripe_coupon_id, max_uses, current_uses, discount_type, discount_value
                    FROM coupons 
                    WHERE coupon_code = %s
                    FOR UPDATE
                """, (discount_code,))
                
                coupon = cursor.fetchone()
                if coupon:
                    discount_type = coupon['discount_type']
                    discount_value = coupon['discount_value']
                    
                    cursor.execute("""
                        UPDATE coupons 
                        SET current_uses = current_uses + 1 
                        WHERE coupon_code = %s
                        AND current_uses < max_uses
                    """, (discount_code,))
                    
                    cursor.execute("""
                        SELECT current_uses, max_uses 
                        FROM coupons 
                        WHERE coupon_code = %s
                    """, (discount_code,))
                    result = cursor.fetchone()
                    
                    if result and result['current_uses'] >= result['max_uses']:
                        from routes.coupons import CouponManager
                        CouponManager.disable_stripe_coupon(
                            coupon['stripe_coupon_id'],
                            discount_code
                        )

            # Créer le token
            expiration_date = datetime.utcnow() + timedelta(days=180)
            tokens_to_create = 2  # Nombre de tokens à créer pour ce pack

            created_tokens = []
            for i in range(tokens_to_create):
                token_code = str(uuid.uuid4())
                
                cursor.execute("""
                    INSERT INTO tokens (
                        token_code, user_id, quiz_id, product_id, item_id,
                        country_code, token_type, is_used, expiration_date,
                        order_id, coupon_code
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    token_code,
                    order_info['user_id'],
                    quiz_id,
                    product_info['product_id'],
                    product_info['item_id'],
                    order_info['country_code'],
                    'paid',
                    False,
                    expiration_date,
                    order_info['order_id'],
                    discount_code
                ))
                
                created_tokens.append(token_code)
                logger.info(f"✅ Token {i+1}/{tokens_to_create} créé: {token_code}")

            # Utiliser le premier token pour l'email de confirmation
            token_code = created_tokens[0]

            
            mysql.connection.commit()
            logger.info(f"✅ Paiement traité avec succès - Token: {token_code}")

            try:
                cursor.execute('''
                    INSERT INTO activity_logs 
                    (user_id, session_id, event_type, page_path, device_type, extra_data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (
                    order_info['user_id'],
                    None,
                    'purchase',
                    '/buy/bilan_carriere_express_fr',
                    stripe_session.metadata.get('device_type', None),
                    json.dumps({
                        'order_number': order_number,
                        'product_id': product_info['product_id'],
                        'amount': final_amount / 100,
                        'bilan_slug': stripe_session.metadata.get('bilan_slug', ''),
                        'bilan_source': stripe_session.metadata.get('bilan_source', ''),
                        'bilan_variant': stripe_session.metadata.get('bilan_variant', ''),
                        'bilan_campaign': stripe_session.metadata.get('bilan_campaign', ''),
                    })
                ))
                mysql.connection.commit()
                logger.info(f"✅ Activity log purchase enregistré pour user {order_info['user_id']}")
            except Exception as tracking_error:
                logger.warning(f"Activity tracking purchase failed: {tracking_error}")

            # Activer le compte si c'est un lead + générer magic link
            magic_url = activate_pending_user(order_info['user_id'], order_info['user_email'], order_info.get('firstname') or order_info['username'], product_id=product_info['product_id'])
            
            # Préparer les données de commande
            order_data = {
                'order_number': order_number,
                'quiz_name': product_info['product_name'],
                'token_code': token_code,
                'expiration_date': expiration_date.strftime("%d/%m/%Y %H:%M"),
                'original_amount': f"{order_info['origin_order_amount']/100:.2f}",
                'base_amount': f"{order_info['base_amount']/100:.2f}",
                'vat_amount': f"{order_info['vat_amount']/100:.2f}",
                'total_amount': f"{final_amount/100:.2f}",
                'currency': 'EUR',
                'user_email': order_info['user_email'],
                'username': order_info['username'],
                'firstname': order_info['firstname'],
                'now': datetime.now()
            }
            
            if discount_code:
                order_data['discount_code'] = discount_code
                order_data['discount_type'] = discount_type
                order_data['discount_value'] = discount_value
                order_data['discount_amount'] = f"{discount_amount/100:.2f}"
            
            # Envoyer l'email approprié selon le type de produit
            is_smart_contact = 'smart_contact' in (product_info['product_id'] or '')
            is_bilan = 'bilan_carriere_express' in (product_info['product_id'] or '')

            if is_bilan:
                from services import send_bilan_purchase_email
                email_sent = send_bilan_purchase_email(
                    email=order_info['user_email'],
                    firstname=order_info.get('firstname') or order_info['username'],
                    order_data=order_data,
                    magic_url=magic_url
                )
            elif is_smart_contact:
                # Email fusionné : confirmation + magic link (1 seul email)
                from services import send_smart_contact_purchase_email
                
                # magic_url est retourné par activate_pending_user (appelé juste avant)
                # Si None (user déjà actif), générer un nouveau magic link
                if not magic_url:
                    import secrets as sec
                    magic_token = sec.token_urlsafe(32)
                    magic_expiry = datetime.utcnow() + timedelta(hours=48)
                    cursor2 = current_app.mysql.connection.cursor(DictCursor)
                    cursor2.execute("""
                        UPDATE users SET invite_token = %s, invite_expiry = %s WHERE user_id = %s
                    """, (magic_token, magic_expiry, order_info['user_id']))
                    current_app.mysql.connection.commit()
                    cursor2.close()
                    base_url = current_app.config.get('BASE_URL', '').rstrip('/')
                    next_path = url_for('dashboard.smart_contact_onboarding')
                    magic_url = f"{base_url}{url_for('auth.magic_login', token=magic_token)}?next={next_path}"
                
                email_sent = send_smart_contact_purchase_email(
                    email=order_info['user_email'],
                    firstname=order_info.get('firstname') or order_info['username'],
                    order_data=order_data,
                    magic_url=magic_url
                )
            else:
                # Produits classiques : email de confirmation standard
                email_sent = send_purchase_confirmation_email(order_info['user_email'], order_data)
            
            if email_sent:
                logger.info(f"Email de confirmation envoyé à {order_info['user_email']}")

        except Exception as db_error:
            mysql.connection.rollback()
            logger.error(f"❌ Erreur base de données: {str(db_error)}", exc_info=True)
            try:
                from services import slack_service, SLACK_AVAILABLE
                if SLACK_AVAILABLE and slack_service:
                    slack_service.send_message(
                        channel='#alerts-paiement',
                        text=f"🚨 PAIEMENT ENCAISSÉ NON LIVRÉ\n"
                             f"• Order: {order_number}\n"
                             f"• Email: {stripe_session.customer_details.email if stripe_session.customer_details else 'inconnu'}\n"
                             f"• Montant: {stripe_session.amount_total/100:.2f}€\n"
                             f"• Erreur: {str(db_error)[:200]}\n"
                             f"• Action: vérifier la commande en base et relancer manuellement"
                    )
            except Exception as slack_err:
                logger.error(f"Slack error: {slack_err}")
            raise db_error

    except Exception as e:
        logger.error(f"❌ Erreur traitement: {str(e)}", exc_info=True)
        raise

    finally:
        if 'cursor' in locals():
            cursor.close()


def trigger_analysis_generation_async(user_id, quiz_id, order_id):
    """
    Déclenche la génération d'analyse via Cloud Tasks (asynchrone).
    ✅ Cette fonction ne bloque PAS la requête HTTP.
    
    Pourquoi Cloud Tasks ?
    - ✅ Asynchrone : La requête HTTP retourne immédiatement
    - ✅ Retry automatique : Si échec, Cloud Tasks réessaie (max 3 fois)
    - ✅ Timeout 60 min : Parfait pour une génération de 1 min
    - ✅ Monitoring : Logs dans Google Cloud Console
    - ✅ Pas de serveur supplémentaire : Utilise ton Cloud Run existant
    """
    logger = logging.getLogger('token_bp')
    
    try:
        # 1. Insérer dans la queue DB (statut: pending)
        cursor = current_app.mysql.connection.cursor(DictCursor)
        
        cursor.execute("""
            INSERT INTO analysis_queue (user_id, quiz_id, order_id, analysis_status)
            VALUES (%s, %s, %s, 'pending')
        """, (user_id, quiz_id, order_id))
        
        queue_id = cursor.lastrowid
        current_app.mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Queue entry created - ID: {queue_id}, User: {user_id}, Quiz: {quiz_id}")
        
        # 2. Créer une tâche Cloud Tasks
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(
            current_app.config['CLOUD_TASKS_PROJECT'],
            current_app.config['CLOUD_TASKS_LOCATION'],
            current_app.config['CLOUD_TASKS_QUEUE']
        )
        
        # URL de l'endpoint qui va traiter la génération
        task_url = f"{current_app.config['BASE_URL']}/internal/process-analysis"
        
        # Payload avec les infos nécessaires
        payload = {
            'user_id': user_id,
            'quiz_id': quiz_id,
            'order_id': order_id,
            'queue_id': queue_id
        }
        
        # Configuration de la tâche
        task = {
            'http_request': {
                'http_method': tasks_v2.HttpMethod.POST,
                'url': task_url,
                'headers': {
                    'Content-Type': 'application/json',
                    'X-Cloud-Tasks-Secret': current_app.config['CLOUD_TASKS_SECRET']
                },
                'body': json.dumps(payload).encode()
            }
        }
        
        # Envoyer la tâche à Cloud Tasks
        response = client.create_task(request={'parent': parent, 'task': task})
        
        logger.info(f"✅ Cloud Task created - Task name: {response.name}")
        
        # 3. Envoyer email "Analyse en cours"
        send_analysis_started_email(user_id, quiz_id)
        
    except Exception as e:
        logger.error(f"❌ Erreur déclenchement Cloud Task: {str(e)}", exc_info=True)


@token_bp.route('/redeem-coupon', methods=['POST'])
def redeem_coupon():
    """Gère la validation d'un coupon et crée un token gratuit."""
    data = request.get_json()
    logger.debug(f"Received data for redeem_coupon: {data}")
    
    coupon_code = data.get('coupon_code')
    
    if not coupon_code:
        logger.warning("Missing coupon_code for redeem_coupon")
        return jsonify({'error': _('Coupon code is required')}), 400
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        mysql.connection.begin()
        
        user_country_code = current_user.country_code.upper() if current_user.country_code else ''
        logger.debug(f"Normalized User Country Code: {user_country_code}")
        
        # Vérifier la validité du coupon
        cursor.execute("""
            SELECT quiz_id, max_uses, current_uses, country_code, start_date, end_date 
            FROM coupons 
            WHERE coupon_code = %s 
            AND (start_date IS NULL OR start_date <= NOW())
            AND (end_date IS NULL OR end_date >= NOW())
            AND (country_code = %s OR country_code = 'ALL')
            FOR UPDATE
        """, (coupon_code, user_country_code))
        
        coupon = cursor.fetchone()
        if not coupon:
            logger.warning(f"Coupon invalide ou expiré: {coupon_code}")
            mysql.connection.rollback()
            return jsonify({'error': _('Invalid or expired coupon code')}), 400

        fetched_quiz_id = coupon['quiz_id']
        if coupon['current_uses'] >= coupon['max_uses']:
            logger.warning(f"Coupon {coupon_code} a atteint le nombre maximum d'utilisations")
            mysql.connection.rollback()
            return jsonify({'error': _('This coupon has reached its maximum number of uses')}), 400

        # Vérifier le quiz
        cursor.execute("""
            SELECT is_active FROM quiz_catalog 
            WHERE quiz_id = %s AND is_active = TRUE
        """, (fetched_quiz_id,))
        if not cursor.fetchone():
            logger.warning(f"Quiz associé au coupon {coupon_code} est invalide ou inactif")
            mysql.connection.rollback()
            return jsonify({'error': _('The quiz associated with this coupon is invalid or inactive')}), 400

        # Vérifier les tokens existants
        cursor.execute("""
            SELECT token_code FROM tokens 
            WHERE user_id = %s AND quiz_id = %s AND is_used = FALSE 
            AND (expiration_date IS NULL OR expiration_date > NOW())
            FOR UPDATE
        """, (current_user.id, fetched_quiz_id))
        
        if cursor.fetchone():
            logger.info(f"L'utilisateur {current_user.id} possède déjà un token actif pour le quiz {fetched_quiz_id}")
            mysql.connection.rollback()
            return jsonify({
                'message': _('You already have an active token for this quiz'),
                'redirect_url': url_for('quiz.display_quiz', quiz_id=fetched_quiz_id)
            }), 200

        # Récupérer les informations produit via product_items
        cursor.execute("""
            SELECT 
                pc.product_id, 
                pci.item_id 
            FROM product_catalog pc
            JOIN product_items pi ON pc.product_id = pi.product_id
            JOIN product_catalog_items pci ON pi.item_id = pci.item_id
            WHERE pi.product_id = pc.product_id
            AND pci.item_id = pi.item_id
            AND pc.product_id IN (
                SELECT pi.product_id
                FROM product_items pi
                WHERE pi.item_id = %s
                AND pi.country_code = %s
                AND pi.quantity > 0
                LIMIT 1
            )
            LIMIT 1
        """, (fetched_quiz_id, user_country_code))
        
        product_item = cursor.fetchone()
        if not product_item:
            logger.warning(f"Aucun produit actif trouvé pour quiz_id {fetched_quiz_id}")
            mysql.connection.rollback()
            return jsonify({'error': _('No active product found for this quiz')}), 400

        # Créer le token
        token_code = str(uuid.uuid4())
        expiration_date = datetime.now() + timedelta(days=30)

        cursor.execute("""
            INSERT INTO tokens (
                token_code, user_id, quiz_id, product_id, item_id, 
                country_code, token_type, is_used, expiration_date, coupon_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            token_code, current_user.id, fetched_quiz_id,
            product_item['product_id'], product_item['item_id'],
            coupon['country_code'], 'free', False,
            expiration_date, coupon_code
        ))

        mysql.connection.commit()
        logger.info(f"Coupon {coupon_code} réclamé avec succès par l'utilisateur {current_user.id}")
        
        return jsonify({
            'message': _('Coupon redeemed successfully'),
            'token': token_code,
            'expiration_date': expiration_date.isoformat(),
            'redirect_url': url_for('quiz.display_quiz', quiz_id=fetched_quiz_id)
        }), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error redeeming coupon: {str(e)}")
        return jsonify({'error': _('An error occurred while redeeming the coupon')}), 500

    finally:
        cursor.close()

@token_bp.route('/use-token/<string:quiz_id>', methods=['POST'])
def use_token(quiz_id):
    """Marque un token comme utilisé pour un quiz spécifique."""
    try:
        data = request.get_json()
        token_code = data.get('token_code')

        if not token_code:
            logger.warning("Token code manquant lors de l'utilisation")
            return jsonify({'error': _('Token code is required')}), 400

        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)

        cursor.execute("""
            SELECT quiz_id, is_used, expiration_date, coupon_code 
            FROM tokens 
            WHERE token_code = %s AND user_id = %s
            FOR UPDATE
        """, (token_code, current_user.id))

        token = cursor.fetchone()

        if not token:
            logger.warning(f"Token invalide: {token_code} pour l'utilisateur {current_user.id}")
            mysql.connection.rollback()
            return jsonify({'error': _('Invalid token')}), 400

        if token['is_used']:
            logger.warning(f"Token déjà utilisé: {token_code} pour l'utilisateur {current_user.id}")
            mysql.connection.rollback()
            return jsonify({'error': _('Token has already been used')}), 400

        if token['expiration_date'] and token['expiration_date'] < datetime.now():
            logger.warning(f"Token expiré: {token_code} pour l'utilisateur {current_user.id}")
            mysql.connection.rollback()
            return jsonify({'error': _('Token has expired')}), 400

        # Marquer le token comme utilisé
        cursor.execute("""
            UPDATE tokens 
            SET is_used = TRUE, used_at = NOW()
            WHERE token_code = %s
        """, (token_code,))

        # Mettre à jour l'utilisation du coupon si applicable
        if token['coupon_code']:
            cursor.execute("""
                UPDATE coupons 
                SET current_uses = current_uses + 1 
                WHERE coupon_code = %s AND max_uses > current_uses
            """, (token['coupon_code'],))

        mysql.connection.commit()
        logger.info(f"Token {token_code} utilisé avec succès par l'utilisateur {current_user.id}")

        return jsonify({'message': _('Token used successfully')}), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error using token: {str(e)}")
        return jsonify({'error': _('An error occurred while using the token')}), 500

    finally:
        cursor.close()

@token_bp.route('/get-token', methods=['GET'])
def get_token():
    """Affiche la boutique avec les produits disponibles."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    try:
        cursor.execute("""
            SELECT DISTINCT
                pc.product_id,
                pc.product_name,
                pc.unit_amount,
                GROUP_CONCAT(DISTINCT qc.quiz_id) as quiz_ids,
                GROUP_CONCAT(DISTINCT qc.quiz_type) as quiz_types
            FROM product_catalog pc
            JOIN product_items pi ON pc.product_id = pi.product_id
            JOIN product_catalog_items pci ON pi.item_id = pci.item_id
            JOIN item_quiz iq ON pci.item_id = iq.item_id
            JOIN quiz_catalog qc ON iq.quiz_id = qc.quiz_id
            WHERE pc.is_active = TRUE
            AND pc.country_code = %s
            GROUP BY pc.product_id, pc.product_name, pc.unit_amount
        """, (current_user.country_code.upper(),))
        
        products_db = cursor.fetchall()
        
        # Récupérer les IDs Stripe depuis la configuration
        is_production = bool(os.getenv('GOOGLE_CLOUD_PROJECT'))
        env = 'prod' if is_production else 'dev'
        logger.info(f"🎨 Environnement Stripe: {env}")
        logger.info(f"🔑 Clé publique utilisée: {current_app.config['STRIPE_PUBLIC_KEY'][:20]}...")
        logger.info(f"🛒 Session créée: {stripe_session.url}")
        stripe_products = current_app.config.get('STRIPE_PRODUCTS', {})
        
        logger.debug(f"Environment: {env}")
        logger.debug(f"Stripe Products config: {stripe_products}")
        logger.debug(f"Products from DB: {len(products_db)}")
        
        products = []
        for p in products_db:
            # Vérifier si on a une configuration spécifique pour ce produit
            stripe_config = stripe_products.get(p['product_id'], {}).get(env, {})
            stripe_price_id = stripe_config.get('stripe_price_id')
            
            # Ne pas afficher les produits sans stripe_price_id valide
            if not stripe_price_id:
                logger.warning(f"Produit {p['product_id']} sans stripe_price_id valide, non affiché")
                continue
                
            products.append({
                'product_id': p['product_id'],
                'product_name': p['product_name'],
                'price_id': stripe_price_id,
                'price': round(p['unit_amount'] / 100, 2),
                'quiz_ids': p['quiz_ids'].split(',') if p['quiz_ids'] else [],
                'quiz_types': p['quiz_types'].split(',') if p['quiz_types'] else []
            })

        return render_template(
            'order/shop.html',
            products=products,
            stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY']
        )
    except Exception as e:
        logger.error(f"Error fetching products: {e}")
        return render_template('order/shop.html', products=[], 
            stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'])
    finally:
        cursor.close()

@token_bp.route('/apply-coupon-code', methods=['POST'])
def apply_coupon_code():
    """
    Vérifie et calcule la remise associée à un coupon pour un produit donné.
    Renvoie un montant de remise en euros.
    """
    data = request.get_json()
    product_id = data.get('product_id')
    coupon_code = data.get('coupon_code')

    if not product_id or not coupon_code:
        return jsonify({'error': _('Paramètres manquants')}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Récupérer les informations du produit (prix unitaire, TVA, etc.)
        cursor.execute("""
            SELECT unit_amount
            FROM product_catalog
            WHERE product_id = %s
            AND is_active = TRUE
        """, (product_id,))
        product = cursor.fetchone()
        if not product:
            return jsonify({'error': _('Produit introuvable ou inactif')}), 404

        # Récupérer les informations du coupon
        cursor.execute("""
            SELECT discount_type, discount_value, max_uses, current_uses, start_date, end_date 
            FROM coupons
            WHERE coupon_code = %s
            AND (start_date IS NULL OR start_date <= NOW())
            AND (end_date IS NULL OR end_date >= NOW())
            LIMIT 1
        """, (coupon_code,))
        coupon = cursor.fetchone()
        if not coupon:
            return jsonify({'error': _('Coupon invalide ou expiré')}), 400

        # Vérifier si le coupon a atteint son nombre maximal d'utilisations
        if coupon['current_uses'] >= coupon['max_uses']:
            return jsonify({'error': _('Coupon a atteint le max d\'utilisations')}), 400

        # Récupérer le prix TTC du produit en centimes
        unit_amount_cents = product['unit_amount']
        
        # Convertir le montant TTC en euros
        unit_amount_eur = unit_amount_cents / 100.0

        # Calcul de la remise
        if coupon['discount_type'] == 'percentage':
            # Si la remise est en pourcentage (ex: 10% de réduction)
            discount_eur = unit_amount_eur * (coupon['discount_value'] / 100.0)
        else:
            # Si la remise est en montant fixe (ex: 5€ de réduction)
            discount_eur = coupon['discount_value'] / 100.0

        # S'assurer que la remise n'excède pas le prix du produit
        if discount_eur > unit_amount_eur:
            discount_eur = unit_amount_eur

        # Retourner le montant de la remise calculée
        return jsonify({
            'discount_amount': round(discount_eur, 2)  # Retourne la remise en euros, arrondie à 2 décimales
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error applying coupon code: {str(e)}")
        return jsonify({'error': _('Erreur interne lors de l\'application du coupon')}), 500
    finally:
        cursor.close()

def get_stripe_events_status(days_ago: int = 30) -> Tuple[List[Dict], List[Dict]]:
    """
    Compare les événements Stripe avec la base de données pour identifier les anomalies.
    Returns:
        Tuple contenant:
        - Liste des événements manquants dans stripe_events
        - Liste des événements sans commande associée
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Date de début pour l'audit
        start_date = int((datetime.now() - timedelta(days=days_ago)).timestamp())
        
        # 1. Récupérer tous les événements Stripe
        stripe_events = stripe.Event.list(
            type='checkout.session.completed',
            created={'gte': start_date},
            limit=100  # Ajustez selon vos besoins
        )
        
        # 2. Récupérer les événements de notre DB
        cursor.execute("""
            SELECT 
                se.stripe_event_id,
                se.status,
                se.created_at,
                se.processed_at,
                se.error,
                o.order_id,
                o.order_number,
                o.user_id,
                o.status as order_status
            FROM stripe_events se
            LEFT JOIN orders o ON o.stripe_session_id = se.stripe_event_id
            WHERE se.event_type = 'checkout.session.completed'
            AND se.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        """, (days_ago,))
        
        db_events = {row['stripe_event_id']: row for row in cursor.fetchall()}
        
        # Pour stocker les anomalies trouvées
        missing_events = []
        orphan_events = []
        
        # 3. Analyser chaque événement Stripe
        for event in stripe_events.auto_paging_iter():
            session = event.data.object
            
            if session.payment_status == 'paid':
                # Vérifier si l'événement est dans notre DB
                db_event = db_events.get(event.id)
                
                if not db_event:
                    # Événement manquant dans stripe_events
                    missing_events.append({
                        'stripe_event_id': event.id,
                        'stripe_session_id': session.id,
                        'customer_email': session.customer_details.email if session.customer_details else None,
                        'amount': session.amount_total,
                        'created_at': datetime.fromtimestamp(event.created),
                        'metadata': session.metadata
                    })
                elif not db_event['order_id'] and db_event['status'] == 'completed':
                    # Événement traité mais pas de commande associée
                    orphan_events.append({
                        'stripe_event_id': event.id,
                        'stripe_session_id': session.id,
                        'db_status': db_event['status'],
                        'processed_at': db_event['processed_at'],
                        'error': db_event['error'],
                        'customer_email': session.customer_details.email if session.customer_details else None,
                        'amount': session.amount_total,
                        'created_at': datetime.fromtimestamp(event.created),
                        'metadata': session.metadata
                    })
        
        return missing_events, orphan_events

    except stripe.error.StripeError as e:
        logger.error(f"Erreur Stripe lors de l'audit: {str(e)}")
        raise
    
    except Exception as e:
        logger.error(f"Erreur lors de l'audit: {str(e)}")
        raise
    
    finally:
        cursor.close()

def format_audit_results(missing_events: List[Dict], orphan_events: List[Dict]) -> str:
    """
    Formate les résultats de l'audit pour affichage.
    """
    if not missing_events and not orphan_events:
        return "✅ Aucune anomalie détectée"
    
    output = []
    
    if missing_events:
        output.append(f"❌ Événements manquants dans stripe_events ({len(missing_events)}):")
        for event in missing_events:
            output.extend([
                f"  ID Événement: {event['stripe_event_id']}",
                f"  Session ID: {event['stripe_session_id']}",
                f"  Email client: {event['customer_email']}",
                f"  Montant: {event['amount']/100:.2f} EUR",
                f"  Date: {event['created_at']}",
                f"  Metadata: {event['metadata']}",
                ""
            ])
    
    if orphan_events:
        output.append(f"⚠️ Événements sans commande ({len(orphan_events)}):")
        for event in orphan_events:
            output.extend([
                f"  ID Événement: {event['stripe_event_id']}",
                f"  Session ID: {event['stripe_session_id']}",
                f"  Email client: {event['customer_email']}",
                f"  Montant: {event['amount']/100:.2f} EUR",
                f"  Date création: {event['created_at']}",
                f"  Date traitement: {event['processed_at']}",
                f"  Statut DB: {event['db_status']}",
                f"  Erreur: {event['error'] or 'Aucune'}",
                f"  Metadata: {event['metadata']}",
                ""
            ])
    
    return "\n".join(output)

def fix_missing_event(stripe_event_id: str) -> Optional[str]:
    """
    Tente de réparer un événement manquant en le réinsérant dans stripe_events.
    Retourne l'erreur si échec, None si succès.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer l'événement depuis Stripe
        event = stripe.Event.retrieve(stripe_event_id)
        
        mysql.connection.begin()
        
        # Vérifier si l'événement n'existe pas déjà
        cursor.execute("""
            SELECT id FROM stripe_events WHERE stripe_event_id = %s
        """, (stripe_event_id,))
        
        if cursor.fetchone():
            return "Événement déjà présent dans la base"
        
        # Insérer l'événement
        cursor.execute("""
            INSERT INTO stripe_events (
                stripe_event_id, event_type, status, 
                created_at, processed_at, error
            ) VALUES (%s, %s, %s, NOW(), NOW(), NULL)
        """, (
            event.id,
            event.type,
            'completed' if event.data.object.payment_status == 'paid' else 'error'
        ))
        
        mysql.connection.commit()
        return None
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la réparation de l'événement {stripe_event_id}: {str(e)}")
        return str(e)
        
    finally:
        cursor.close()

@token_bp.route('/admin/stripe-audit', methods=['GET'])
@admin_required
def stripe_audit():
    """Page d'audit des événements Stripe."""
    try:
        # Récupérer la date de début depuis les paramètres de l'URL
        start_date = request.args.get('start_date')
        days_ago = 30  # Valeur par défaut
        
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d')
                days_ago = (datetime.now() - start_date).days
                if days_ago < 0:
                    days_ago = 30
            except ValueError:
                days_ago = 30
        
        # Récupérer les anomalies
        missing_events, orphan_events = get_stripe_events_status(days_ago=days_ago)
        
        if request.headers.get('Accept') == 'application/json':
            return jsonify({
                'missing_events': missing_events,
                'orphan_events': orphan_events,
                'total_issues': len(missing_events) + len(orphan_events)
            })
            
        return render_template(
            'admin/stripe_audit.html',
            missing_events=missing_events,
            orphan_events=orphan_events,
            missing_count=len(missing_events),
            orphan_count=len(orphan_events)
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de l'audit Stripe: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@token_bp.route('/admin/stripe-audit/fix', methods=['POST'])
@admin_required
def fix_stripe_audit():
    """Tente de réparer les événements manquants."""
    data = request.get_json()
    event_id = data.get('event_id')
    
    if not event_id:
        return jsonify({'error': 'event_id requis'}), 400
        
    error = fix_missing_event(event_id)
    
    if error:
        return jsonify({
            'status': 'error',
            'message': f"Échec de la réparation: {error}"
        }), 400
        
    return jsonify({
        'status': 'success',
        'message': 'Événement réparé avec succès'
    })

@token_bp.route('/terms-and-conditions')
def terms_and_conditions():
    """Affiche les conditions générales de vente."""
    from datetime import datetime
    return render_template('order/terms_and_conditions.html', now=datetime.now())


@token_bp.route('/checkout-continue')
@login_required
def checkout_continue():
    # Récupérer product_id depuis les arguments ou la session (sans pop pour ne pas perdre en cas de redirect)
    product_id = request.args.get('product_id') or session.get('checkout_product_id')
    coupon_code = request.args.get('coupon_code') or session.get('checkout_coupon_code', '')

    if not product_id:
        flash(_("Votre session d'achat a expiré. Veuillez réessayer."), "error")
        return redirect(url_for('tokens.shop'))

    try:
        # Construire la session Stripe avec l'utilisateur authentifié
        stripe_session = build_stripe_checkout_session(current_user, product_id, coupon_code)
        
        # Nettoyer la session maintenant que Stripe est créé avec succès
        session.pop('checkout_product_id', None)
        session.pop('checkout_coupon_code', None)
        session.pop('after_login_redirect', None)
        
        # Mode embedded → render template avec client_secret
        if stripe_session.client_secret:
            return render_template(
                'order/embedded_checkout.html',
                client_secret=stripe_session.client_secret,
                stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'],
                product_id=product_id
            )
        
        # Mode hosted (fallback) → redirect vers URL Stripe
        if stripe_session.url:
            return redirect(stripe_session.url, code=303)
        
        logger.error(f"Session Stripe sans client_secret ni URL: {stripe_session.id}")
        flash(_('Erreur lors de la création de la session de paiement.'), 'error')
        return redirect(url_for('tokens.shop'))

    except Exception as e:
        logger.error(f"Erreur lors du checkout continue: {e}", exc_info=True)
        flash(_('Une erreur est survenue lors du paiement.'), 'error')
        return redirect(url_for('tokens.shop'))


def build_stripe_checkout_session(user, product_id, coupon_code=None):
    """
    Prépare et crée la session Stripe de paiement.
    Utilisé à la fois pour les utilisateurs connectés directement ou après auth.
    
    Args:
        user: Objet utilisateur (current_user), ou None pour guest checkout.
              Pour les produits guest (ex: bilan_carriere_express_fr), user peut être None.
              L'utilisateur sera créé/retrouvé dans handle_successful_payment via l'email Stripe.
        product_id: ID du produit à acheter
        coupon_code: Code promo optionnel (depuis URL ou formulaire)
    
    Returns:
        stripe.checkout.Session: Session Stripe créée
    """
    # Guest checkout : user peut être None pour certains produits
    GUEST_CHECKOUT_PRODUCTS = {'bilan_carriere_express_fr'}
    is_guest = user is None
    if is_guest and product_id not in GUEST_CHECKOUT_PRODUCTS:
        raise Exception(_('Ce produit nécessite une connexion avant l\'achat'))
    country_code = user.country_code.upper() if user else 'FR'
    user_id = user.id if user else None

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        mysql.connection.begin()

        # ==================== 1. RÉCUPÉRER LE PRODUIT ====================
        cursor.execute("""
            SELECT 
                pc.*, iq.quiz_id,
                pci.item_id
            FROM product_catalog pc
            JOIN product_items pi ON pc.product_id = pi.product_id
            JOIN product_catalog_items pci ON pi.item_id = pci.item_id
            JOIN item_quiz iq ON pci.item_id = iq.item_id
            WHERE pc.product_id = %s 
            AND pc.is_active = TRUE
            AND pc.country_code = %s
            LIMIT 1
        """, (product_id, country_code))
        
        product = cursor.fetchone()
        if not product:
            raise Exception(_('Produit non trouvé ou inactif'))

        # ==================== 2. RÉCUPÉRER LA CONFIG STRIPE ====================
        is_production = bool(os.getenv('GOOGLE_CLOUD_PROJECT'))
        env = 'prod' if is_production else 'dev'
        stripe_products = current_app.config.get('STRIPE_PRODUCTS', {})
        stripe_config = stripe_products.get(product_id, {}).get(env, {})
        stripe_price_id = stripe_config.get('stripe_price_id')

        if not stripe_price_id:
            raise Exception(_('Configuration Stripe incomplète'))

        # ==================== 3. CALCULER LES MONTANTS ====================
        apply_vat = current_app.config.get('APPLY_VAT', False)
        vat_rate = current_app.config.get('VAT_RATE', 20.0)

        base_price = product['base_price'] if apply_vat else product['unit_amount']
        vat_price = product['vat_price'] if apply_vat else 0

        # ==================== 4. VALIDER LE COUPON ====================
        discount_code_to_store = None
        stripe_discount = None
        
        if coupon_code:
            logger.info(f"🎟️ Tentative d'application du coupon: {coupon_code}")
            
            cursor.execute("""
                SELECT 
                    stripe_coupon_id, 
                    discount_type, 
                    discount_value, 
                    current_uses, 
                    max_uses,
                    country_code
                FROM coupons
                WHERE coupon_code = %s
                AND (start_date IS NULL OR start_date <= NOW())
                AND (end_date IS NULL OR end_date >= NOW())
                AND (country_code = %s OR country_code = 'ALL')
                AND current_uses < max_uses
            """, (coupon_code, country_code))
            
            coupon = cursor.fetchone()
            
            if coupon and coupon['stripe_coupon_id']:
                discount_code_to_store = coupon_code
                stripe_discount = [{'coupon': coupon['stripe_coupon_id']}]
                logger.info(f"✅ Coupon valide: {coupon_code}")
                logger.info(f"   - Type: {coupon['discount_type']}")
                logger.info(f"   - Valeur: {coupon['discount_value']}")
                logger.info(f"   - Stripe ID: {coupon['stripe_coupon_id']}")
                logger.info(f"   - Utilisations: {coupon['current_uses']}/{coupon['max_uses']}")
            else:
                logger.warning(f"❌ Coupon invalide, expiré ou épuisé: {coupon_code}")
                # Ne pas bloquer le processus, juste ignorer le coupon invalide
                coupon_code = None

        # ==================== 5. CRÉER LA COMMANDE ====================
        order_number = generate_order_number()
        
        cursor.execute("""
            INSERT INTO orders (
                order_number, user_id, base_amount, vat_amount, order_amount,
                origin_order_amount, discount_amount, discount_code,
                currency, status, country_code, stripe_session_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            order_number,
            user_id,          # None pour guest, sera mis à jour dans le webhook
            base_price, 
            vat_price, 
            product['unit_amount'],
            product['unit_amount'], 
            0,                # Le montant de réduction sera calculé par Stripe
            discount_code_to_store,
            'EUR', 
            'pending',
            country_code,
            None
        ))
        order_id = cursor.lastrowid
        logger.info(f"📝 Commande créée: {order_number} (ID: {order_id}), guest={is_guest}")

        # ==================== 6. CRÉER ORDER_PRODUCT ====================
        cursor.execute("""
            INSERT INTO order_product (
                order_id, product_id, quantity, unit_price,
                base_amount, vat_amount, vat_rate,
                product_amount, origin_product_amount,
                discount_amount, currency, country_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            order_id, 
            product_id, 
            1, 
            product['unit_amount'], 
            base_price, 
            vat_price,
            vat_rate, 
            product['unit_amount'], 
            product['unit_amount'], 
            0,                # Sera mis à jour par le webhook
            'EUR', 
            country_code
        ))

        # ==================== 7. CRÉER ORDER_ITEM ====================
        cursor.execute("""
            INSERT INTO order_item (
                order_id, product_id, item_id, quantity, unit_price,
                base_amount, vat_amount, vat_rate, item_amount,
                currency, country_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            order_id, 
            product_id, 
            product['item_id'], 
            1, 
            product['unit_amount'], 
            base_price,
            vat_price, 
            vat_rate, 
            product['unit_amount'], 
            'EUR', 
            country_code
        ))

        # ==================== 8. CRÉER LA SESSION STRIPE ====================
        session_data = {
            'mode': 'payment',
            'ui_mode': 'embedded',
            'return_url': url_for('tokens.checkout_return', _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            'line_items': [{'price': stripe_price_id, 'quantity': 1}],
            'metadata': {
                'order_number': order_number,
                'quiz_id': product['quiz_id'],
                'bilan_slug': session.get('bilan_flash_slug', ''),
                'bilan_variant': session.get('bilan_flash_meta', {}).get('variant', ''),
                'bilan_source': session.get('bilan_flash_meta', {}).get('source', ''),
                'bilan_campaign': session.get('bilan_flash_meta', {}).get('campaign', ''),
                'device_type': 'mobile' if any(m in (request.user_agent.string or '').lower() for m in ['iphone', 'android', 'mobile']) else 'desktop',
            }
        }

        # Appliquer le discount validé
        if stripe_discount:
            session_data['discounts'] = stripe_discount
            logger.info(f"💰 Discount appliqué à la session Stripe: {stripe_discount}")
        else:
            session_data['allow_promotion_codes'] = True
            logger.info(f"ℹ️ Aucun discount appliqué, codes promo manuels autorisés")

        # Créer la session Stripe
        stripe_session = stripe.checkout.Session.create(**session_data)
        logger.info(f"✅ Session Stripe créée: {stripe_session.id}")
        logger.debug(f"   URL: {stripe_session.url}")

        # ==================== 9. METTRE À JOUR LA COMMANDE ====================
        cursor.execute("""
            UPDATE orders SET stripe_session_id = %s WHERE order_id = %s
        """, (stripe_session.id, order_id))

        # ==================== 10. COMMIT ====================
        mysql.connection.commit()
        logger.info(f"✅ Commande {order_number} créée avec succès")
        
        return stripe_session

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"❌ Erreur création session Stripe: {str(e)}", exc_info=True)
        raise e

    finally:
        cursor.close()

@token_bp.route('/order/status')
def order_status():
    """Polling endpoint — vérifie si la commande est passée à paid."""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'status': 'unknown'}), 400
    cursor = current_app.mysql.connection.cursor(DictCursor)
    try:
        cursor.execute("""
            SELECT status FROM orders 
            WHERE stripe_session_id = %s
        """, (session_id,))
        order = cursor.fetchone()
        return jsonify({'status': order['status'] if order else 'pending'})
    except Exception as e:
        logger.error(f"Erreur order_status: {e}")
        return jsonify({'status': 'pending'})
    finally:
        cursor.close()
        
@token_bp.route('/buy/<string:product_id>', methods=['GET', 'POST'])
def direct_buy(product_id: str):
    """
    Lien direct vers le paiement.
    GET = utilisateur connecté
    POST = depuis landing (email dans le body)
    """
    try:
        coupon_code = request.args.get('coupon', '').strip() or request.form.get('coupon', '').strip()

        # CAS 1 : Utilisateur déjà connecté → flow normal
        if current_user.is_authenticated:
            stripe_session = build_stripe_checkout_session(current_user, product_id, coupon_code)
            return render_template(
                'order/embedded_checkout.html',
                client_secret=stripe_session.client_secret,
                stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'],
                product_id=product_id
            )

        # ── GUEST CHECKOUT (pas d'email requis avant paiement) ──────────────
        GUEST_CHECKOUT_PRODUCTS = {'bilan_carriere_express_fr'}
        if product_id in GUEST_CHECKOUT_PRODUCTS:
            stripe_session = build_stripe_checkout_session(None, product_id, coupon_code)
            return render_template(
                'order/embedded_checkout.html',
                client_secret=stripe_session.client_secret,
                stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'],
                product_id=product_id
            )
        # ── FIN GUEST CHECKOUT ───────────────────────────────────────────────
        # CAS 2 : Non connecté — récupérer l'email (POST depuis landing)
        email = (request.form.get('email') or request.args.get('email') or '').strip().lower()

        if not email or '@' not in email:
            session['checkout_product_id'] = product_id
            session['checkout_coupon_code'] = coupon_code
            session['after_login_redirect'] = url_for('tokens.checkout_continue')
            return redirect(url_for('auth.login'))

        status, user = get_or_create_pending_user(email)

        if status == 'existing':
            # User connu → doit se connecter via la page login standard
            session['checkout_product_id'] = product_id
            session['checkout_coupon_code'] = coupon_code
            session['after_login_redirect'] = url_for('tokens.checkout_continue')
            flash(_('Un compte existe avec cet email. Connectez-vous pour continuer.'), 'info')
            return redirect(url_for('auth.login'))

        if status == 'error' or not user:
            flash(_('Une erreur est survenue. Veuillez réessayer.'), 'error')
            return redirect(request.referrer or url_for('tokens.shop'))

        # status == 'created' → nouveau lead, continuer vers checkout
        session['smart_contact_email'] = email

        stripe_session = build_stripe_checkout_session(user, product_id, coupon_code)
        return render_template(
            'order/embedded_checkout.html',
            client_secret=stripe_session.client_secret,
            stripe_public_key=current_app.config['STRIPE_PUBLIC_KEY'],
            product_id=product_id
        )

    except Exception as e:
        logger.error(f"Error in direct_buy: {e}", exc_info=True)
        flash(_('Une erreur est survenue. Veuillez réessayer.'), 'error')
        return redirect(request.referrer or url_for('tokens.shop'))
@token_bp.route('/checkout/return')
def checkout_return():
    """
    Gère le retour après paiement avec le checkout intégré.
    Vérifie le statut et redirige vers success ou cancel.
    """
    session_id = request.args.get('session_id')
    
    if not session_id:
        return redirect(url_for('tokens.payment_failed', error='invalid_session'))
    
    try:
        # Récupérer le statut de la session
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        
        if stripe_session.payment_status == 'paid':
            return redirect(url_for('tokens.success', session_id=session_id))
        else:
            return redirect(url_for('tokens.cancel', session_id=session_id))
            
    except Exception as e:
        logger.error(f"Erreur lors du retour checkout: {e}")
        return redirect(url_for('tokens.payment_failed', error='checkout_error'))

@token_bp.route('/my-tokens', methods=['GET'])
@login_required
def get_my_tokens():
    """Récupère les tokens disponibles de l'utilisateur."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                t.token_code,
                t.quiz_id,
                t.product_id,
                t.token_type,
                t.expiration_date,
                t.is_used,
                pc.product_name
            FROM tokens t
            LEFT JOIN product_catalog pc ON t.product_id = pc.product_id
            WHERE t.user_id = %s 
            AND t.is_used = FALSE
            AND (t.expiration_date IS NULL OR t.expiration_date > NOW())
            ORDER BY t.expiration_date ASC
        """, (current_user.id,))
        
        tokens = cursor.fetchall()
        
        for token in tokens:
            if token['expiration_date']:
                token['expiration_date'] = token['expiration_date'].isoformat()
        
        return jsonify({
            'success': True,
            'tokens': tokens,
            'count': len(tokens)
        })
        
    except Exception as e:
        logger.error(f"Error fetching user tokens: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()


@token_bp.route('/use-for-piste', methods=['POST'])
@login_required  
def use_token_for_piste():
    """Utilise un token pour débloquer une piste d'analyse."""
    data = request.json
    
    token_code = data.get('token_code')  # Changé de token_id à token_code
    piste_number = data.get('piste_number')
    quiz_id = data.get('quiz_id')
    user_id = data.get('user_id')
    
    if not token_code or not piste_number:
        return jsonify({'success': False, 'error': 'token_code et piste_number requis'}), 400
    
    target_user_id = current_user.id
    if user_id and current_user.user_status in ('admin', 'coach'):
        target_user_id = int(user_id)
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Pour les admins : chercher le token dans les tokens de l'admin OU du user cible
        if current_user.user_status in ('admin', 'coach'):
            cursor.execute("""
                SELECT token_code, quiz_id, is_used, expiration_date, user_id
                FROM tokens
                WHERE token_code = %s 
                AND user_id IN (%s, %s)
                AND is_used = FALSE
                AND (expiration_date IS NULL OR expiration_date > NOW())
                FOR UPDATE
            """, (token_code, current_user.id, target_user_id))
        else:
            cursor.execute("""
                SELECT token_code, quiz_id, is_used, expiration_date, user_id
                FROM tokens
                WHERE token_code = %s 
                AND user_id = %s
                AND is_used = FALSE
                AND (expiration_date IS NULL OR expiration_date > NOW())
                FOR UPDATE
            """, (token_code, target_user_id))
        
        token = cursor.fetchone()
        
        if not token:
            return jsonify({'success': False, 'error': 'Token invalide ou déjà utilisé'}), 400
        
        cursor.execute("""
            UPDATE tokens 
            SET is_used = TRUE, 
                used_at = NOW(),
                used_for_piste = %s
            WHERE token_code = %s
        """, (piste_number, token_code))
        
        cursor.execute("""
            INSERT INTO user_unlocked_pistes (user_id, quiz_id, piste_number, token_code, unlocked_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE unlocked_at = NOW(), token_code = %s
        """, (target_user_id, quiz_id or token['quiz_id'], piste_number, token_code, token_code))
        
        current_app.mysql.connection.commit()
        
        logger.info(f"Token {token_code} utilisé pour piste {piste_number} par user {target_user_id}")
        
        return jsonify({
            'success': True,
            'message': f'Piste {piste_number} débloquée !',
            'piste_number': piste_number
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Error using token for piste: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()


@token_bp.route('/unlocked-pistes/<string:quiz_id>', methods=['GET'])
@login_required
def get_unlocked_pistes(quiz_id):
    """Récupère les pistes débloquées pour un quiz."""
    user_id = request.args.get('user_id')
    
    target_user_id = current_user.id
    if user_id and current_user.user_status in ('admin', 'coach'):
        target_user_id = int(user_id)
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT piste_number, unlocked_at
            FROM user_unlocked_pistes
            WHERE user_id = %s AND quiz_id = %s
        """, (target_user_id, quiz_id))
        
        unlocked = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'unlocked_pistes': [row['piste_number'] for row in unlocked],
            'details': unlocked
        })
        
    except Exception as e:
        logger.error(f"Error fetching unlocked pistes: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()

def get_or_create_pending_user(email):
    """Crée un compte lead si l'email est inconnu. Retourne ('existing', None) si le user existe déjà."""
    import secrets as sec
    cursor = current_app.mysql.connection.cursor(DictCursor)

    try:
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()

        if existing:
            return 'existing', None  # ← signal : user existe, doit se connecter

        username = email.split('@')[0][:80]
        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE username = %s", (username,))
        if cursor.fetchone()['cnt'] > 0:
            username = f"{username}_{sec.token_hex(3)}"

        cursor.execute("""
            INSERT INTO users (username, email, password, user_status, country_code,
                               lead_source, onboarding_stage, created_at)
            VALUES (%s, %s, NULL, 'lead', 'FR', 'landing_direct_buy', 'invited', NOW())
        """, (username, email))

        user_id = cursor.lastrowid
        current_app.mysql.connection.commit()
        logger.info(f"✅ Compte pending créé: user_id={user_id}, email={email}")

        return 'created', User(user_id=user_id, username=username, email=email,
                                user_status='lead', country_code='FR')

    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Erreur création pending user: {e}", exc_info=True)
        return 'error', None
    finally:
        cursor.close()

def activate_pending_user(user_id, email, firstname, product_id=None):
    """Active un lead → user après paiement et retourne le magic_url."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    try:
        cursor.execute("SELECT user_status FROM users WHERE user_id = %s", (user_id,))
        user_data = cursor.fetchone()
        if not user_data:
            return None

        if user_data['user_status'] == 'lead':
            cursor.execute("""
                UPDATE users SET user_status = 'user', onboarding_stage = 'email_verified', updated_at = NOW()
                WHERE user_id = %s AND user_status = 'lead'
            """, (user_id,))
            current_app.mysql.connection.commit()
            logger.info(f"✅ User {user_id} activé: lead → user")

        # Générer un magic link 48h pour accéder au compte
        import secrets as sec
        magic_token = sec.token_urlsafe(32)
        magic_expiry = datetime.utcnow() + timedelta(hours=48)

        cursor.execute("""
            UPDATE users SET invite_token = %s, invite_expiry = %s, updated_at = NOW()
            WHERE user_id = %s
        """, (magic_token, magic_expiry, user_id))
        current_app.mysql.connection.commit()

        # Construire le magic_url avec BASE_URL (pas request.host_url qui donne ngrok)
        base_url = current_app.config.get('BASE_URL', '').rstrip('/')
        magic_path = url_for('auth.magic_login', token=magic_token)
        
        is_smart_contact = 'smart_contact' in (product_id or '')
        is_bilan = 'bilan_carriere_express' in (product_id or '')

        if is_smart_contact:
            next_path = url_for('dashboard.smart_contact_onboarding')
            magic_url = f"{base_url}{magic_path}?next={next_path}"
        elif is_bilan:
            next_path = url_for('dashboard.index')
            magic_url = f"{base_url}{magic_path}?next={next_path}"
        else:
            magic_url = f"{base_url}{magic_path}"

        logger.info(f"✅ Magic link 48h généré pour user {user_id}, redirect={'onboarding' if is_smart_contact else 'dashboard'}")
        return magic_url

    except Exception as e:
        logger.error(f"Erreur activation user {user_id}: {e}", exc_info=True)
        return None
    finally:
        cursor.close()


BLOCKED_DOMAINS = [
    'hello.com', 'test.com', 'example.com', 'mailinator.com',
    'tempmail.com', 'guerrillamail.com', 'yopmail.com', 'throwaway.email'
]


@token_bp.route('/smart-contact/confirm/<string:product_id>', methods=['POST'])
@limiter.limit("5 per minute")
@limiter.limit("10 per hour")
def smart_contact_confirm(product_id: str):
    """
    Étape intermédiaire Smart Contact.
    POST depuis la landing (email dans le body) :
      1. Honeypot anti-bot
      2. Rate limiting (via décorateurs)
      3. Validation email + blocage domaines suspects
      4. Crée le user lead via get_or_create_pending_user
      5. Log le user en session Flask-Login
      6. Redirige vers la page de réassurance
    """
    # request_id pour le tracking dans les logs
    if not hasattr(g, 'request_id') or not g.request_id:
        g.request_id = str(uuid.uuid4())

    try:
        # ── 1. HONEYPOT ──────────────────────────────────────────────────────
        honeypot = request.form.get('website', '').strip()
        if honeypot:
            logger.warning(f"[{g.request_id}] 🤖 Bot détecté smart_contact - honeypot: '{honeypot}'")
            # Réponse silencieuse : on redirige comme si tout allait bien
            return redirect(url_for(
                'tokens.smart_contact_confirm_page', product_id=product_id
            ))

        # ── 2. RÉCUPÉRATION ──────────────────────────────────────────────────
        email = (request.form.get('email') or '').strip().lower()
        coupon_code = request.form.get('coupon', '').strip()

        # ── 3. VALIDATION EMAIL ──────────────────────────────────────────────
        if not email or '@' not in email:
            flash(_('Adresse email invalide.'), 'error')
            return redirect(url_for('tilto_smart_contacts', slug_id=session.get('smart_contact_slug', '8793')))

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash(_('Adresse email invalide.'), 'error')
            return redirect(url_for('tilto_smart_contacts', slug_id=session.get('smart_contact_slug', '8793')))

        # ── 4. BLOCAGE DOMAINES SUSPECTS ─────────────────────────────────────
        email_domain = email.split('@')[-1].lower()
        if email_domain in BLOCKED_DOMAINS:
            logger.warning(f"[{g.request_id}] 🤖 Bot détecté smart_contact - domaine bloqué: {email_domain}")
            # Réponse silencieuse : on redirige comme si tout allait bien
            return redirect(url_for(
                'tokens.smart_contact_confirm_page', product_id=product_id
            ))

        logger.info(f"[{g.request_id}] Smart contact confirm - email: {email}, product: {product_id}")

        # ── 5. CRÉATION DU LEAD ───────────────────────────────────────────────
        # ── 5. CRÉATION DU LEAD ───────────────────────────────────────────────
        if current_user.is_authenticated and current_user.email == email:
            user = current_user
            logger.info(f"[{g.request_id}] User déjà connecté avec le même email, skip création lead")

        else:
            # Déconnecter si connecté avec un email différent
            if current_user.is_authenticated and current_user.email != email:
                from flask_login import logout_user
                logout_user()

            status, user = get_or_create_pending_user(email)

            if status == 'existing':
                session['checkout_product_id'] = product_id
                session['checkout_coupon_code'] = coupon_code
                session['after_login_redirect'] = url_for(
                    'tokens.smart_contact_confirm_page', product_id=product_id
                )
                flash(_('Un compte existe avec cet email. Connectez-vous pour continuer.'), 'info')
                return redirect(url_for('auth.login'))

            if status == 'error' or not user:
                flash(_('Une erreur est survenue. Veuillez réessayer.'), 'error')
                return redirect(url_for('tilto_smart_contacts', slug_id=session.get('smart_contact_slug', '8793')))

            from flask_login import login_user
            login_user(user, remember=False)

        # ── 6. SESSION ────────────────────────────────────────────────────────
        session['smart_contact_email'] = email
        session['smart_contact_product_id'] = product_id
        session['smart_contact_coupon'] = coupon_code

        # Notification Slack (non bloquant)
        try:
            from services import slack_service, SLACK_AVAILABLE
            if SLACK_AVAILABLE and slack_service:
                slack_service.notify_new_lead({
                    'user_id': user.id,
                    'email': email,
                    'firstname': '',
                    'lastname': '',
                    'profile': 'smart_contact_lead',
                    'source': 'landing_smart_contact',
                    'lead_interest': 'smart_contact',
                    'has_quiz_answers': False,
                    'has_audio_responses': False,
                    'newsletter_subscription': False,
                })
        except Exception as slack_err:
            logger.error(f"[{g.request_id}] Slack error (non-blocking): {slack_err}")

        logger.info(f"[{g.request_id}] ✅ Smart contact lead créé et connecté: user_id={user.id}")

        return redirect(url_for(
            'tokens.smart_contact_confirm_page', product_id=product_id
        ))

    except Exception as e:
        logger.error(f"[{g.request_id}] Error in smart_contact_confirm: {e}", exc_info=True)
        flash(_('Une erreur est survenue. Veuillez réessayer.'), 'error')
        return redirect(url_for('tilto_smart_contacts', slug_id=session.get('smart_contact_slug', '8793')))


@token_bp.route('/smart-contact/votre-pack/<string:product_id>', methods=['GET'])
def smart_contact_confirm_page(product_id: str):
    """
    Page de réassurance avant paiement.
    Le user lead est déjà créé et connecté en session Flask-Login à ce stade.
    Le bouton "Payer" dans le template pointe vers :
        url_for('tokens.direct_buy', product_id=product_id)  (GET)
    direct_buy détecte current_user.is_authenticated → True et lance
    directement build_stripe_checkout_session sans redemander l'email.
    """
    if not current_user.is_authenticated and 'smart_contact_email' not in session:
        return redirect(url_for('tilto_smart_contacts', slug_id=session.get('smart_contact_slug', '8793')))

    coupon_code = session.get('smart_contact_coupon', '')

    return render_template(
        'pages/smart_contact_confirm.html',
        product_id=product_id,
        coupon_code=coupon_code,
        email=session.get('smart_contact_email', '')
    )

@token_bp.route('/api/smart-contact/save-phone', methods=['POST'])
@login_required
def smart_contact_save_phone():
    """
    Sauvegarde le numéro de téléphone après achat Smart Contact.
    Appelé depuis la page de confirmation de commande.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Données manquantes'}), 400

        phone = data.get('phone', '').strip()
        order_id = data.get('order_id')

        # Validation basique
        if not phone or len(phone) < 8:
            return jsonify({'success': False, 'message': 'Numéro de téléphone invalide'}), 400

        # Nettoyer le numéro (garder chiffres, +, espaces, tirets)
        import re
        phone_clean = re.sub(r'[^\d\+\s\-\.]', '', phone).strip()

        cursor = current_app.mysql.connection.cursor()

        # Mettre à jour le numéro de téléphone de l'utilisateur
        cursor.execute("""
            UPDATE users 
            SET phone_number = %s,
                updated_at = NOW()
            WHERE user_id = %s
        """, (phone_clean, current_user.id))

        # Si un order_id est fourni, le logger aussi (optionnel mais utile pour le suivi)
        if order_id:
            try:
                cursor.execute("""
                    UPDATE orders
                    SET metadata = JSON_SET(
                        COALESCE(metadata, '{}'),
                        '$.callback_phone', %s,
                        '$.callback_requested_at', NOW()
                    )
                    WHERE id = %s AND user_id = %s
                """, (phone_clean, order_id, current_user.id))
            except Exception as e:
                # Non bloquant si la table orders n'a pas de colonne metadata
                logger.warning(f"[smart_contact_save_phone] Impossible de logger sur la commande: {e}")

        current_app.mysql.connection.commit()
        cursor.close()

        logger.info(f"[smart_contact_save_phone] Téléphone enregistré pour user {current_user.id}: {phone_clean}")

        # Notifier Slack si disponible
        from services import slack_service, SLACK_AVAILABLE
        if SLACK_AVAILABLE and slack_service:
            try:
                slack_service.send_message(
                    channel='#smart-contact',
                    text=f"📞 Nouveau numéro Smart Contact\n"
                         f"• Utilisateur : {current_user.email}\n"
                         f"• Téléphone : {phone_clean}\n"
                         f"• Commande : #{order_id or 'N/A'}"
                )
            except Exception as e:
                logger.warning(f"[smart_contact_save_phone] Erreur Slack: {e}")

        return jsonify({'success': True, 'message': 'Numéro enregistré'}), 200

    except Exception as e:
        logger.error(f"[smart_contact_save_phone] Erreur: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Une erreur est survenue'}), 500

@token_bp.route('/lead/discovery-call', methods=['POST'])
@csrf.exempt  
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def create_discovery_call_lead():
    """
    Crée un lead depuis la landing pack session (appel découverte).
    Pas d'email — identifiant unique = numéro de téléphone.
    """
    if not hasattr(g, 'request_id') or not g.request_id:
        g.request_id = str(uuid.uuid4())

    try:
        data = request.get_json(silent=True) or request.form

        # ── 1. HONEYPOT ──────────────────────────────────────────────────────
        if data.get('_hp_email', '').strip():
            logger.warning(f"[{g.request_id}] 🤖 Bot détecté discovery-call lead")
            return jsonify({'success': True, 'message': 'Merci, on vous recontacte très vite !'}), 200

        # ── 2. RÉCUPÉRATION DES CHAMPS ───────────────────────────────────────
        firstname     = (data.get('firstname') or '').strip()
        lastname      = (data.get('lastname') or '').strip()
        phone_raw     = (data.get('phone_number') or '').strip()
        lead_interest = (data.get('lead_interest') or '').strip()

        # ── 3. VALIDATION ────────────────────────────────────────────────────
        errors = {}
        if not firstname:
            errors['firstname'] = 'Le prénom est requis.'
        if not lastname:
            errors['lastname'] = 'Le nom est requis.'
        if not lead_interest:
            errors['lead_interest'] = 'Merci de sélectionner votre situation.'

        # Nettoyage + validation téléphone FR
        phone = re.sub(r'[\s.\-]', '', phone_raw)
        phone_re = re.compile(r'^(\+33|0033|0)[67][0-9]{8}$|^(\+33|0033)[1-9][0-9]{8}$|^0[1-9][0-9]{8}$')
        if not phone:
            errors['phone_number'] = 'Le numéro de téléphone est requis.'
        elif not phone_re.match(phone):
            errors['phone_number'] = 'Ce numéro ne semble pas valide.'

        if errors:
            return jsonify({'success': False, 'errors': errors}), 400

        # Normalisation téléphone → format +33
        if phone.startswith('0'):
            phone = '+33' + phone[1:]
        elif phone.startswith('0033'):
            phone = '+33' + phone[4:]

        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)

        try:
            # ── 4. VÉRIFICATION DOUBLON ──────────────────────────────────────
            cursor.execute("""
                SELECT user_id, firstname, lastname
                FROM users
                WHERE phone_number = %s
            """, (phone,))

            existing = cursor.fetchone()
            if existing:
                logger.info(f"[{g.request_id}] Téléphone déjà enregistré: {phone}")
                return jsonify({
                    'success': False,
                    'errors': {
                        'phone_number': 'Ce numéro est déjà enregistré. Vous allez être recontacté(e) très prochainement !'
                    }
                }), 409

            # ── 5. GÉNÉRATION USERNAME ───────────────────────────────────────
            base_username = f"{firstname.lower()}.{lastname.lower()}"
            base_username = re.sub(r'[^a-z0-9._-]', '', base_username)[:60]
            username = base_username

            cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE username = %s", (username,))
            if cursor.fetchone()['cnt'] > 0:
                username = f"{base_username}_{uuid.uuid4().hex[:4]}"

            # ── 6. INSERTION EN BASE ─────────────────────────────────────────
            cursor.execute("""
                INSERT INTO users (
                    username, firstname, lastname,
                    email,
                    phone_number, lead_interest,
                    user_status, country_code,
                    lead_source, onboarding_stage,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    NULL,
                    %s, %s,
                    'lead', 'FR',
                    'landing_pack_tilto', 'invited',
                    NOW(), NOW()
                )
            """, (username, firstname, lastname, phone, lead_interest))

            user_id = cursor.lastrowid
            mysql.connection.commit()

            logger.info(f"[{g.request_id}] ✅ Lead discovery créé: user_id={user_id}, phone={phone}")

            # ── 7. NOTIFICATION SLACK ────────────────────────────────────────
            try:
                from services import slack_service, SLACK_AVAILABLE
                if SLACK_AVAILABLE and slack_service:
                    slack_service.notify_new_lead({
                        'user_id':               user_id,
                        'email':                 None,
                        'firstname':             firstname,
                        'lastname':              lastname,
                        'phone_number':          phone,
                        'profile':               'discovery_call_lead',
                        'source':                'landing_pack_tilto',
                        'lead_interest':         lead_interest,
                        'has_quiz_answers':      False,
                        'has_audio_responses':   False,
                        'newsletter_subscription': False,
                    })
            except Exception as slack_err:
                logger.error(f"[{g.request_id}] Slack error (non-blocking): {slack_err}")

            return jsonify({
                'success': True,
                'message': 'Merci !'
            }), 201

        except Exception as db_err:
            mysql.connection.rollback()
            logger.error(f"[{g.request_id}] DB error: {db_err}", exc_info=True)
            return jsonify({'success': False, 'message': 'Une erreur est survenue. Veuillez réessayer.'}), 500

        finally:
            cursor.close()

    except Exception as e:
        logger.error(f"[{g.request_id}] Error create_discovery_call_lead: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Une erreur est survenue. Veuillez réessayer.'}), 500