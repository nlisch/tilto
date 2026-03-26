# coupons.py
import logging
from flask import Blueprint, jsonify, request, render_template, current_app, url_for, redirect
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from decorators import admin_required
import stripe
from MySQLdb.cursors import DictCursor
from flask_babel import _
import uuid
import json
import os

coupons_bp = Blueprint('coupons', __name__)
logger = logging.getLogger(__name__)

class CouponManager:
    """Gestionnaire de coupons pour synchroniser Stripe et la base de données."""

    @staticmethod
    def create_stripe_coupon(data):
        """Crée un coupon et son code promotionnel dans Stripe."""
        try:
            # 1. Créer le coupon Stripe
            coupon_data = {
                'duration': 'once',
                'name': data.get('description', data['coupon_code'])
            }

            if data['discount_type'] == 'percentage':
                coupon_data['percent_off'] = float(data['discount_value'])
            else:
                # La valeur est déjà en centimes depuis le frontend
                coupon_data['amount_off'] = int(data['discount_value'])
                coupon_data['currency'] = 'eur'

            if data.get('end_date'):
                coupon_data['redeem_by'] = int(datetime.strptime(
                    data['end_date'], '%Y-%m-%d %H:%M:%S'
                ).timestamp())

            if data.get('max_uses'):
                coupon_data['max_redemptions'] = int(data['max_uses'])

            # Ajouter les restrictions de produit
            if data.get('product_id'):
                # Récupérer les IDs Stripe depuis la configuration
                is_production = bool(os.getenv('GOOGLE_CLOUD_PROJECT'))
                env = 'prod' if is_production else 'dev'
                stripe_products = current_app.config.get('STRIPE_PRODUCTS', {})
                
                # Chercher d'abord dans la configuration
                stripe_product_id = None
                if data['product_id'] in stripe_products:
                    stripe_config = stripe_products.get(data['product_id'], {}).get(env, {})
                    stripe_product_id = stripe_config.get('stripe_product_id')
                
                # Si pas trouvé dans la config, chercher dans la base de données
                if not stripe_product_id:
                    mysql = current_app.mysql
                    cursor = mysql.connection.cursor(DictCursor)
                    try:
                        cursor.execute("""
                            SELECT stripe_product_id
                            FROM product_catalog
                            WHERE product_id = %s
                        """, (data['product_id'],))
                        product = cursor.fetchone()
                        if product and product['stripe_product_id']:
                            stripe_product_id = product['stripe_product_id']
                    finally:
                        cursor.close()
                
                if stripe_product_id:
                    coupon_data['applies_to'] = {
                        'products': [stripe_product_id]
                    }
                    logger.debug(f"Coupon restreint au produit Stripe ID: {stripe_product_id}")
                else:
                    logger.warning(f"Stripe Product ID non trouvé pour {data['product_id']}")

            coupon = stripe.Coupon.create(**coupon_data)
            logger.info(f"Coupon Stripe créé: {coupon.id}")

            # 2. Créer le code promotionnel
            promo_data = {
                'code': data['coupon_code'],
                'coupon': coupon.id,
                'max_redemptions': int(data.get('max_uses', 1)),
                'active': True
            }

            if data.get('min_purchase_amount'):
                promo_data['restrictions'] = {
                    'minimum_amount': int(float(data.get('min_purchase_amount')) * 100),
                    'minimum_amount_currency': 'eur'
                }

            promo_code = stripe.PromotionCode.create(**promo_data)
            logger.info(f"Code promotionnel créé: {promo_code.code}")

            return {'coupon': coupon, 'promo_code': promo_code}

        except Exception as e:
            logger.error(f"Erreur création coupon Stripe: {str(e)}")
            if 'coupon' in locals():
                try:
                    stripe.Coupon.delete(coupon.id)
                    logger.info(f"Coupon {coupon.id} supprimé après erreur")
                except Exception as cleanup_error:
                    logger.error(f"Erreur nettoyage: {str(cleanup_error)}")
            raise

    @staticmethod
    def verify_stripe_coupon(coupon_code, stripe_coupon_id):
        """Vérifie la validité complète d'un coupon dans Stripe."""
        logger = logging.getLogger(__name__)
        try:
            # 1. Vérifier le coupon
            try:
                coupon = stripe.Coupon.retrieve(stripe_coupon_id)
                if not coupon or not coupon.valid:
                    logger.info(f"Coupon {stripe_coupon_id} invalide ou supprimé")
                    return False
            except stripe.error.InvalidRequestError:
                logger.info(f"Coupon {stripe_coupon_id} non trouvé dans Stripe")
                return False

            # 2. Vérifier le code promo associé
            promo_codes = stripe.PromotionCode.list(
                coupon=stripe_coupon_id,
                code=coupon_code,
                limit=1
            )
            
            if not promo_codes.data:
                logger.info(f"Code promo {coupon_code} non trouvé")
                return False

            promo = promo_codes.data[0]
            if not promo.active:
                logger.info(f"Code promo {coupon_code} inactif")
                return False

            # 3. Vérifier les limites d'utilisation
            if (promo.max_redemptions and 
                promo.times_redeemed >= promo.max_redemptions):
                logger.info(f"Code promo {coupon_code} a atteint max_redemptions")
                return False

            # 4. Vérifier l'expiration
            if (coupon.redeem_by and 
                datetime.fromtimestamp(coupon.redeem_by) < datetime.now()):
                logger.info(f"Coupon {stripe_coupon_id} expiré")
                return False

            return True

        except stripe.error.StripeError as e:
            logger.error(f"Erreur Stripe lors de la vérification: {str(e)}")
            return False

    @staticmethod
    def disable_stripe_coupon(stripe_coupon_id, coupon_code):
        """Désactive complètement un coupon dans Stripe en désactivant tous ses codes promotionnels."""
        logger = logging.getLogger(__name__)
        try:
            # 1. Récupérer et désactiver tous les codes promotionnels associés au coupon
            promo_codes = stripe.PromotionCode.list(
                coupon=stripe_coupon_id,
                active=True,
                limit=100  # Ajustez la limite selon vos besoins
            )
            
            for promo_code in promo_codes.data:
                try:
                    stripe.PromotionCode.modify(
                        promo_code.id,
                        active=False
                    )
                    logger.info(f"Code promotionnel {promo_code.code} désactivé avec succès.")
                except stripe.error.StripeError as e:
                    logger.error(f"Erreur lors de la désactivation du code promo {promo_code.code}: {str(e)}")
                    raise  # Relever l'exception pour gérer le rollback si nécessaire

            # 2. Optionnel : Mettre à jour votre base de données pour marquer le coupon comme désactivé
            # Exemple :
            # cursor.execute("""
            #     UPDATE coupons 
            #     SET is_active = FALSE 
            #     WHERE stripe_coupon_id = %s
            # """, (stripe_coupon_id,))
            # mysql.connection.commit()

            logger.info(f"Tous les codes promotionnels pour le coupon {stripe_coupon_id} ont été désactivés.")
            return True

        except stripe.error.StripeError as e:
            logger.error(f"Erreur Stripe lors de la désactivation du coupon {stripe_coupon_id}: {str(e)}")
            raise  # Relever l'exception pour gérer le rollback si nécessaire
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la désactivation du coupon {stripe_coupon_id}: {str(e)}")
            raise  # Relever l'exception pour gérer le rollback si nécessaire



    @staticmethod
    def increment_usage(coupon_code, stripe_coupon_id=None):
        """Incrémente l'utilisation d'un coupon et le désactive si nécessaire."""
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            cursor.execute("""
                UPDATE coupons 
                SET current_uses = current_uses + 1 
                WHERE coupon_code = %s
                AND current_uses < max_uses
                RETURNING current_uses, max_uses
            """, (coupon_code,))
            
            result = cursor.fetchone()
            if result and result['current_uses'] >= result['max_uses']:
                if stripe_coupon_id:
                    CouponManager.disable_stripe_coupon(
                        stripe_coupon_id, 
                        coupon_code
                    )
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Erreur incrémentation usage coupon: {str(e)}")
            return False
        
        finally:
            cursor.close()

    @staticmethod
    def delete_stripe_coupon(stripe_coupon_id, coupon_code):
        """Supprime le coupon et désactive les codes promos associés dans Stripe."""
        logger = logging.getLogger(__name__)
        try:
            # 1. Désactiver tous les codes promos associés
            promo_codes = stripe.PromotionCode.list(
                coupon=stripe_coupon_id,
                limit=100
            )
            
            for promo_code in promo_codes.data:
                try:
                    stripe.PromotionCode.modify(
                        promo_code.id,
                        active=False
                    )
                    logger.info(f"Code promo {promo_code.code} désactivé avec succès")
                except stripe.error.StripeError as e:
                    logger.error(f"Erreur désactivation code promo {promo_code.code}: {str(e)}")
                    raise

            # 2. Supprimer directement le coupon
            try:
                stripe.Coupon.delete(stripe_coupon_id)
                logger.info(f"Coupon {stripe_coupon_id} supprimé avec succès")
            except stripe.error.StripeError as e:
                logger.error(f"Erreur suppression coupon {stripe_coupon_id}: {str(e)}")
                raise
            
            return True

        except stripe.error.StripeError as e:
            logger.error(f"Erreur Stripe lors de la suppression: {str(e)}")
            raise

@coupons_bp.route('/coupon_handler', methods=['GET'])
@login_required
@admin_required
def coupon_handler():
    """Affiche la page de gestion des coupons"""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer la liste des produits actifs
        cursor.execute("""
            SELECT product_id, product_name
            FROM product_catalog
            WHERE is_active = TRUE
            AND country_code = %s
            ORDER BY product_name
        """, (current_user.country_code.upper(),))
        
        products = cursor.fetchall()
        
        return render_template(
            'admin/coupon_handler.html',
            datetime=datetime,
            timedelta=timedelta,
            products=products
        )
    except Exception as e:
        logger.error(f"Erreur récupération produits: {str(e)}")
        return render_template(
            'admin/coupon_handler.html',
            datetime=datetime,
            timedelta=timedelta,
            products=[]
        )
    finally:
        cursor.close()

@coupons_bp.route('/admin', methods=['GET'])
@login_required
@admin_required
def admin_panel():
    """Interface d'administration des coupons."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT product_id, product_name
            FROM product_catalog
            WHERE is_active = TRUE
            AND country_code = %s
            ORDER BY product_name
        """, (current_user.country_code.upper(),))
        
        products = cursor.fetchall()
        
        return render_template(
            'admin/coupon_handler.html',
            datetime=datetime,
            products=products
        )
    except Exception as e:
        logger.error(f"Erreur récupération produits: {str(e)}")
        return render_template(
            'admin/coupon_handler.html',
            datetime=datetime,
            products=[]
        )
    finally:
        cursor.close()

@coupons_bp.route('/api/validate', methods=['POST'])
@login_required
def validate_coupon():
    """Valide un coupon et calcule sa remise."""
    data = request.get_json()
    product_id = data.get('product_id')
    coupon_code = data.get('coupon_code')

    if not product_id or not coupon_code:
        return jsonify({'error': _('Paramètres manquants')}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        cursor.execute("""
            SELECT unit_amount 
            FROM product_catalog
            WHERE product_id = %s 
            AND is_active = TRUE
            AND country_code = %s
        """, (product_id, current_user.country_code.upper()))
        
        product = cursor.fetchone()
        if not product:
            return jsonify({'error': _('Produit invalide')}), 404

        cursor.execute("""
            SELECT discount_type, discount_value, max_uses, current_uses,
                   stripe_coupon_id, start_date, end_date, product_id
            FROM coupons
            WHERE coupon_code = %s
            AND product_id = %s
            AND current_uses < max_uses
            AND (country_code = %s OR country_code = 'ALL')
            AND (start_date IS NULL OR start_date <= NOW())
            AND (end_date IS NULL OR end_date >= NOW())
            FOR UPDATE
        """, (coupon_code, product_id, current_user.country_code.upper()))
        
        coupon = cursor.fetchone()
        if not coupon:
            return jsonify({'error': _('Coupon invalide, expiré ou non applicable à ce produit')}), 400

        # Vérifier dans Stripe
        if not CouponManager.verify_stripe_coupon(
            coupon_code, 
            coupon['stripe_coupon_id']
        ):
            return jsonify({'error': _('Code promo non valide')}), 400

        # Calculer la remise
        unit_amount_eur = product['unit_amount'] / 100.0
        if coupon['discount_type'] == 'percentage':
            discount_eur = unit_amount_eur * (coupon['discount_value'] / 100.0)
        else:
            discount_eur = coupon['discount_value'] / 100.0

        # Limiter la remise au prix du produit
        discount_eur = min(discount_eur, unit_amount_eur)

        return jsonify({
            'discount_amount': round(discount_eur, 2),
            'coupon': {
                'type': coupon['discount_type'],
                'value': coupon['discount_value']
            }
        }), 200

    except Exception as e:
        logger.error(f"Erreur validation coupon: {str(e)}")
        return jsonify({'error': _('Erreur interne')}), 500
        
    finally:
        cursor.close()

@coupons_bp.route('/api/coupons', methods=['GET', 'POST'])
@admin_required
def manage_coupons():
    """Gestion CRUD des coupons."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        if request.method == 'POST':
            data = request.get_json()
            required = ['coupon_code', 'product_id', 'discount_type', 'discount_value']
            if not all(field in data for field in required):
                return jsonify({'error': _('Champs requis manquants')}), 400

            # Vérifier l'unicité
            cursor.execute(
                "SELECT 1 FROM coupons WHERE coupon_code = %s",
                (data['coupon_code'],)
            )
            if cursor.fetchone():
                return jsonify({'error': _('Code coupon déjà existant')}), 400

            # Vérifier que le produit existe
            cursor.execute(
                "SELECT 1 FROM product_catalog WHERE product_id = %s AND is_active = TRUE",
                (data['product_id'],)
            )
            if not cursor.fetchone():
                return jsonify({'error': _('Produit invalide ou inactif')}), 400

            # Créer dans Stripe
            stripe_data = CouponManager.create_stripe_coupon(data)

            # Créer en base de données
            cursor.execute("""
                INSERT INTO coupons (
                    coupon_code, product_id, description, discount_type,
                    discount_value, usage_limit_per_user, min_purchase_amount,
                    country_code, max_uses, start_date, end_date, 
                    stripe_coupon_id, current_uses
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['coupon_code'],
                data['product_id'],
                data.get('description', ''),
                data['discount_type'],
                float(data['discount_value']),
                int(data.get('usage_limit_per_user', 1)),
                data.get('min_purchase_amount'),
                data.get('country_code', 'ALL').upper(),
                int(data.get('max_uses', 1)),
                data.get('start_date'),
                data.get('end_date'),
                stripe_data['coupon'].id,
                0
            ))

            mysql.connection.commit()
            return jsonify({
                'success': True,
                'message': _('Coupon créé avec succès'),
                'coupon_id': stripe_data['coupon'].id
            }), 201

        else:  # GET
            cursor.execute("""
                SELECT c.*, pc.product_name 
                FROM coupons c
                JOIN product_catalog pc ON c.product_id = pc.product_id
                ORDER BY c.created_at DESC
            """)
            coupons = cursor.fetchall()
            return jsonify({'coupons': coupons}), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur gestion coupons: {str(e)}")
        return jsonify({'error': str(e)}), 500

    finally:
        cursor.close()

@coupons_bp.route('/api/coupons/<string:coupon_code>', methods=['DELETE'])
@admin_required
def delete_coupon(coupon_code):
    """Supprime complètement un coupon du système."""

    if not request.headers.get('X-CSRFToken'):
        return jsonify({'error': 'CSRF token manquant'}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        mysql.connection.begin()
        
        # 1. Vérifier et récupérer les informations du coupon
        cursor.execute("""
            SELECT stripe_coupon_id, product_id 
            FROM coupons 
            WHERE coupon_code = %s 
            FOR UPDATE
        """, (coupon_code,))
        
        coupon = cursor.fetchone()
        if not coupon:
            return jsonify({'error': _('Coupon non trouvé')}), 404

        # 2. Supprimer dans Stripe d'abord
        try:
            stripe_deleted = CouponManager.delete_stripe_coupon(
                coupon['stripe_coupon_id'],
                coupon_code
            )
            if not stripe_deleted:
                raise Exception("Échec de la suppression dans Stripe")
        except stripe.error.StripeError as e:
            mysql.connection.rollback()
            logger.error(f"Erreur Stripe lors de la suppression: {str(e)}")
            return jsonify({'error': str(e)}), 500

        # 3. Supprimer de la base de données
        cursor.execute("""
            DELETE FROM coupons 
            WHERE coupon_code = %s
        """, (coupon_code,))
        
        # 4. Vérification finale
        cursor.execute("""
            SELECT 1 
            FROM coupons 
            WHERE coupon_code = %s
        """, (coupon_code,))
        
        if cursor.fetchone():
            mysql.connection.rollback()
            return jsonify({
                'error': _('Échec de la suppression du coupon dans la base de données')
            }), 500
        
        mysql.connection.commit()
        return jsonify({
            'success': True,
            'message': _('Coupon supprimé avec succès de Stripe et de la base de données')
        }), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la suppression du coupon: {str(e)}")
        return jsonify({'error': str(e)}), 500

    finally:
        cursor.close()