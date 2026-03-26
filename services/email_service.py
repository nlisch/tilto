import os
import logging
from flask import render_template, current_app, url_for
from flask_mail import Message
from extensions import mail
from datetime import datetime

logger = logging.getLogger(__name__)

def send_email(to_email, subject, html_content, text_content=None):
    """
    Envoie un email via SMTP (Brevo).
    
    Args:
        to_email (str): Adresse email du destinataire
        subject (str): Sujet de l'email
        html_content (str): Contenu HTML de l'email
        text_content (str, optional): Version texte brut de l'email
    
    Returns:
        dict: Résultat de l'envoi d'email avec statut et message
    """
    if text_content is None:
        # Conversion simpliste de HTML en texte brut
        text_content = html_content.replace('<br>', '\n').replace('</p>', '\n')
        text_content = text_content.replace('<p>', '').replace('<h1>', '')
        text_content = text_content.replace('</h1>', '\n').replace('<h2>', '')
        text_content = text_content.replace('</h2>', '\n').replace('<li>', '- ')
        text_content = text_content.replace('</li>', '\n').replace('<ul>', '')
        text_content = text_content.replace('</ul>', '\n').replace('<ol>', '')
        text_content = text_content.replace('</ol>', '\n')
    
    try:
        # Créer le message avec Flask-Mail
        msg = Message(
            subject=subject,
            sender=(
                current_app.config.get('BREVO_FROM_NAME', 'Tilto'),
                current_app.config['MAIL_DEFAULT_SENDER']
            ),
            recipients=[to_email]
        )
        
        msg.body = text_content
        msg.html = html_content
        
        # Envoyer l'email
        mail.send(msg)
        
        logger.info(f"Email envoyé à {to_email} via SMTP")
        
        return {
            "success": True,
            "message": "Email sent successfully"
        }
        
    except Exception as e:
        logger.error(f"Exception lors de l'envoi d'email via SMTP: {e}")
        return {
            "success": False,
            "message": f"Exception: {str(e)}"
        }

def send_purchase_confirmation_email(user_email, order_data):
    """
    Envoie un email de confirmation d'achat à l'utilisateur.
    
    Args:
        user_email (str): Email de l'utilisateur
        order_data (dict): Données de la commande contenant :
            - order_number: Numéro de commande
            - quiz_name: Nom du quiz acheté
            - token_code: Code du jeton
            - expiration_date: Date d'expiration du jeton
            - original_amount: Montant original
            - discount_amount: Montant de la réduction (si applicable)
            - discount_code: Code de réduction (si applicable)
            - discount_type: Type de réduction ('percentage' ou 'fixed')
            - discount_value: Valeur de la réduction
            - total_amount: Montant total
            - currency: Devise
            - vat_amount: Montant de la TVA
    
    Returns:
        bool: True si l'email a été envoyé avec succès, False sinon
    """
    try:
        from datetime import datetime
        
        subject = "Confirmation de votre achat - Tilto"
        
        # Ajouter la date actuelle aux données
        order_data['now'] = datetime.now()
        
        # Générer le contenu HTML
        html_content = render_template(
            'emails/purchase_confirmation.html',
            order=order_data
        )
        
        # Générer le contenu texte
        text_content = render_template(
            'emails/purchase_confirmation.txt',
            order=order_data
        )
        
        # Envoyer l'email
        result = send_email(
            to_email=user_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
        
        if result.get('success', False):
            logger.info(f"Email de confirmation envoyé pour la commande {order_data.get('order_number', 'N/A')} à {user_email}")
            return True
        else:
            logger.error(f"Échec de l'envoi de l'email de confirmation: {result.get('message', 'Erreur inconnue')}")
            return False
        
    except Exception as e:
        logger.error(f"Exception lors de l'envoi de l'email de confirmation pour la commande {order_data.get('order_number', 'unknown')}: {str(e)}", exc_info=True)
        return False

def send_password_reset_email(user_email, reset_url, reset_code=None, username=None, expires_in_hours=None):
    """
    Envoie un email de réinitialisation de mot de passe à l'utilisateur.
    
    Args:
        user_email (str): Email de l'utilisateur
        reset_url (str): URL complète pour la réinitialisation du mot de passe
        reset_code (str, optional): Code de réinitialisation si un code est utilisé
        username (str, optional): Nom d'utilisateur si disponible
        expires_in_hours (int, optional): Durée de validité du lien en heures
    
    Returns:
        bool: True si l'email a été envoyé avec succès, False sinon
    """
    try:
        from datetime import datetime
        
        subject = "Réinitialisation de votre mot de passe - Tilto"
        
        # Données pour le template
        email_data = {
            'reset_url': reset_url,
            'reset_code': reset_code,
            'username': username,
            'email': user_email,
            'expires_in_hours': expires_in_hours,
            'now': datetime.now()
        }
        
        # Générer le contenu HTML
        html_content = render_template('emails/password_reset.html', **email_data)
        
        # Générer le contenu texte
        text_content = render_template('emails/password_reset.txt', **email_data)
        
        # Envoyer l'email
        result = send_email(
            to_email=user_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
        
        if result.get('success', False):
            logger.info(f"Email de réinitialisation de mot de passe envoyé à {user_email}")
            return True
        else:
            logger.error(f"Échec de l'envoi de l'email de réinitialisation: {result.get('message', 'Erreur inconnue')}")
            return False
            
    except Exception as e:
        logger.error(f"Exception lors de l'envoi de l'email de réinitialisation: {str(e)}", exc_info=True)
        return False

def send_invite_email(email, name, token, interest=None, analysis_token=None):
    """
    Envoie un email d'activation avec le token pour créer le mot de passe
    Utilise le template Jinja2 pour un email moderne et responsive
    """
    try:
        # Validation des paramètres d'entrée
        if not email or not name or not token:
            logger.error(f"Paramètres manquants pour l'envoi d'email: email={bool(email)}, name={bool(name)}, token={bool(token)}")
            return False
        
        # Sécuriser le nom pour éviter les injections
        safe_name = name.strip()
        if not safe_name:
            safe_name = "Utilisateur"
        
        # Extraire le prénom (premier mot du nom)
        firstname = safe_name.split()[0] if safe_name else "Utilisateur"
        
        # Générer l'URL d'activation de manière sécurisée
        try:
            activation_link = url_for('lead.activate_account', token=token, _external=True)
        except Exception as url_error:
            logger.error(f"Erreur génération URL d'activation: {str(url_error)}")
            return False
        
        # Validation de l'URL générée
        if not activation_link or not activation_link.startswith(('http://', 'https://')):
            logger.error(f"URL d'activation invalide: {activation_link}")
            return False
        
        # Personnaliser le sujet selon l'intérêt
        if interest == 'recommendations_metier':
            subject = "🎯 Active ton compte pour recevoir tes recommandations - Tilto"
        else:
            subject = "🔐 Active ton compte Tilto - Dernière étape"
        
        # Utiliser le template Jinja2 moderne
        try:
            html_content = render_template(
                'emails/email_activation.html',  # Ton nouveau template
                firstname=firstname,
                activation_link=activation_link,
                now=datetime.now()
            )
        except Exception as template_error:
            logger.error(f"Erreur lors du rendu du template email: {str(template_error)}")
            return False
        
        # Validation du contenu HTML généré
        if len(html_content) > 100000:  # Limite de sécurité
            logger.error(f"Email HTML trop volumineux: {len(html_content)} caractères")
            return False
        
        # Envoyer l'email via le service
        try:
            result = send_email(
                to_email=email,
                subject=subject,
                html_content=html_content
            )
            
            if result:
                logger.info(f"✅ Email d'activation envoyé avec succès à {email}")
                return True
            else:
                logger.error(f"❌ Échec de l'envoi d'email à {email} - service send_email a retourné False")
                return False
                
        except Exception as send_error:
            logger.error(f"❌ Erreur lors de l'appel au service send_email pour {email}: {str(send_error)}")
            return False
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la préparation de l'email d'activation à {email}: {str(e)}", exc_info=True)
        return False

def send_magic_link_email(email, firstname, magic_url, expires_in_minutes=15):
    """
    Envoie un email avec un Magic Link pour connexion sans mot de passe
    
    Args:
        email (str): Email du destinataire
        firstname (str): Prénom du destinataire
        magic_url (str): URL complète du Magic Link
        expires_in_minutes (int): Durée de validité du lien (défaut: 15 min)
    
    Returns:
        bool: True si l'email a été envoyé, False sinon
    """
    try:
        from flask_mail import Message
        from extensions import mail
        from flask import render_template
        from datetime import datetime
        
        subject = f"🔑 Ton lien de connexion Tilto (valable {expires_in_minutes} min)"
        
        html_body = render_template(
            'emails/magic_link.html',
            firstname=firstname,
            magic_url=magic_url,
            expires_in_minutes=expires_in_minutes,
            now=datetime.now()
        )
        
        msg = Message(
            subject=subject,
            sender=('Tilto', 'noreply@tilto.ai'),
            recipients=[email],
            html=html_body
        )
        
        mail.send(msg)
        logger.info(f"✅ Magic Link email envoyé à {email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur envoi Magic Link: {str(e)}", exc_info=True)
        return False

def send_analysis_ready_email(user_email, firstname, analysis_url):
    """
    Envoie un email pour notifier que l'analyse est prête
    
    Args:
        user_email (str): Email de l'utilisateur
        firstname (str): Prénom de l'utilisateur
        analysis_url (str): URL complète vers l'analyse
    
    Returns:
        bool: True si l'email a été envoyé, False sinon
    """
    try:
        subject = "Tes résultats Tilto sont prêts !"
        
        html_content = render_template(
            'emails/analysis_ready.html',
            firstname=firstname,
            analysis_url=analysis_url,
            now=datetime.now()
        )
        
        # ✅ PAS de text_content : send_email() le génère automatiquement depuis le HTML
        result = send_email(
            to_email=user_email,
            subject=subject,
            html_content=html_content
        )
        
        if result.get('success', False):
            logger.info(f"✅ Email 'analyse prête' envoyé à {user_email}")
            return True
        else:
            logger.error(f"❌ Échec envoi email : {result.get('message')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Exception envoi email : {str(e)}", exc_info=True)
        return False

def send_bilan_purchase_email(email, firstname, order_data, magic_url):
    """
    Email post-achat Bilan Carrière Express : confirmation commande + magic link d'accès.
    """
    try:
        subject = "Votre Bilan Carrière Express est confirmé 🎉"

        template_data = {
            'firstname': firstname,
            'email': email,
            'magic_url': magic_url,
            'order_number': order_data.get('order_number', ''),
            'original_amount': order_data.get('original_amount', ''),
            'total_amount': order_data.get('total_amount', ''),
            'vat_amount': order_data.get('vat_amount', ''),
            'discount_code': order_data.get('discount_code'),
            'discount_type': order_data.get('discount_type'),
            'discount_value': order_data.get('discount_value'),
            'discount_amount': order_data.get('discount_amount'),
            'now': datetime.now()
        }

        html_content = render_template('emails/bilan_carriere_express_purchase.html', **template_data)

        result = send_email(
            to_email=email,
            subject=subject,
            html_content=html_content
        )

        if result.get('success', False):
            logger.info(f"✅ Email Bilan Carrière Express envoyé à {email}")
            return True
        else:
            logger.error(f"❌ Échec envoi email Bilan: {result.get('message')}")
            return False

    except Exception as e:
        logger.error(f"❌ Exception envoi email Bilan: {str(e)}", exc_info=True)
        return False

def send_smart_contact_purchase_email(email, firstname, order_data, magic_url):
    """
    Email unique post-achat Smart Contact : confirmation commande + magic link d'accès.
    Remplace les 2 emails séparés (purchase_confirmation + welcome).
    """
    try:
        subject = "Confirmation d'achat — Tilto Smart Contact"

        template_data = {
            'firstname': firstname,
            'email': email,
            'magic_url': magic_url,
            'dashboard_phone_url': magic_url,
            'order_number': order_data.get('order_number', ''),
            'original_amount': order_data.get('original_amount', ''),
            'total_amount': order_data.get('total_amount', ''),
            'vat_amount': order_data.get('vat_amount', ''),
            'discount_code': order_data.get('discount_code'),
            'discount_type': order_data.get('discount_type'),
            'discount_value': order_data.get('discount_value'),
            'discount_amount': order_data.get('discount_amount'),
            'now': datetime.now()
        }

        html_content = render_template('emails/smart_contact_purchase.html', **template_data)

        result = send_email(
            to_email=email,
            subject=subject,
            html_content=html_content
        )

        if result.get('success', False):
            logger.info(f"✅ Email Smart Contact purchase envoyé à {email}")
            return True
        else:
            logger.error(f"❌ Échec envoi email Smart Contact: {result.get('message')}")
            return False

    except Exception as e:
        logger.error(f"❌ Exception envoi email Smart Contact: {str(e)}", exc_info=True)
        return False