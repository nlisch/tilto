"""
Service YouCanBookMe - Gestion des interactions avec l'API YouCanBookMe
Fichier : services/youcanbook_service.py
"""

import logging
import requests
import json
import hashlib
import hmac
from datetime import datetime
from typing import Dict, Any, Optional, List
from flask import current_app

logger = logging.getLogger(__name__)

class YouCanBookMeService:
    """Service pour gérer les interactions avec YouCanBookMe."""
    
    def __init__(self, api_key: str = None, webhook_secret: str = None, subdomain: str = "tilto"):
        """
        Initialise le service YouCanBookMe.
        
        Args:
            api_key: Clé API YouCanBookMe (pour les appels API futurs)
            webhook_secret: Secret pour vérifier les webhooks
            subdomain: Sous-domaine YouCanBookMe (par défaut: tilto)
        """
        self.api_key = api_key
        self.webhook_secret = webhook_secret
        self.subdomain = subdomain
        self.base_url = f"https://api.youcanbook.me/v1"
        
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Vérifie la signature d'un webhook YouCanBookMe.
        
        Args:
            payload: Corps de la requête webhook en bytes
            signature: Signature fournie dans les headers
            
        Returns:
            bool: True si la signature est valide
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret non configuré - signature non vérifiée")
            return True  # En développement, accepter sans vérification
        
        try:
            # YouCanBookMe utilise généralement HMAC-SHA256
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Format attendu : "sha256=..." 
            if signature.startswith('sha256='):
                signature = signature[7:]
            
            return hmac.compare_digest(expected_signature, signature)
            
        except Exception as e:
            logger.error(f"Erreur vérification signature webhook: {str(e)}")
            return False
    
    def parse_webhook_data(self, webhook_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse et normalise les données d'un webhook YouCanBookMe.
        
        Args:
            webhook_data: Données brutes du webhook
            
        Returns:
            Dict contenant les données normalisées ou None si erreur
        """
        try:
            # Déterminer le type d'événement
            event_type = self._determine_event_type(webhook_data)
            
            # Extraire les informations de base
            parsed_data = {
                'event_type': event_type,
                'booking_id': webhook_data.get('id'),
                'start_datetime': self._parse_datetime(webhook_data.get('startsAt') or webhook_data.get('startTime')),
                'end_datetime': self._parse_datetime(webhook_data.get('endsAt') or webhook_data.get('endTime')),
                'timezone': webhook_data.get('timeZone', 'UTC'),
                'duration': webhook_data.get('duration', 60),
                'attendee_email': self._extract_email(webhook_data),
                'attendee_name': self._extract_name(webhook_data),
                'user_id': self._extract_user_id(webhook_data),
                'product_id': self._extract_product_id(webhook_data),
                'zoom_link': webhook_data.get('zoomLink') or webhook_data.get('meetingUrl'),
                'answers': webhook_data.get('answers', {}),
                'form_fields': webhook_data.get('formFields', []),
                'raw_data': webhook_data
            }
            
            logger.info(f"Webhook parsé - Type: {event_type}, Booking ID: {parsed_data['booking_id']}, User ID: {parsed_data['user_id']}")
            return parsed_data
            
        except Exception as e:
            logger.error(f"Erreur parsing webhook data: {str(e)}", exc_info=True)
            return None
    
    def _determine_event_type(self, data: Dict[str, Any]) -> str:
        """Détermine le type d'événement du webhook."""
        event_type = data.get('type', '').lower()
        
        # Mapping des types d'événements YouCanBookMe
        type_mapping = {
            'booking.created': 'booking.created',
            'booking.confirmed': 'booking.created', 
            'new_booking': 'booking.created',
            'booking.cancelled': 'booking.cancelled',
            'booking_cancelled': 'booking.cancelled',
            'booking.rescheduled': 'booking.rescheduled',
            'booking_rescheduled': 'booking.rescheduled',
        }
        
        normalized_type = type_mapping.get(event_type, 'booking.created')
        
        # Détecter l'annulation par la présence de cancelledAt
        if data.get('cancelledAt') or data.get('cancelled_at'):
            normalized_type = 'booking.cancelled'
        
        # Détecter la reprogrammation par la présence de rescheduledAt  
        if data.get('rescheduledAt') or data.get('rescheduled_at'):
            normalized_type = 'booking.rescheduled'
            
        return normalized_type
    
    def _parse_datetime(self, datetime_str: str) -> Optional[datetime]:
        """Parse une chaîne de date/heure YouCanBookMe."""
        if not datetime_str:
            return None
            
        try:
            # Formats possibles de YouCanBookMe
            formats = [
                '%Y-%m-%dT%H:%M:%SZ',           # 2025-05-25T14:00:00Z
                '%Y-%m-%dT%H:%M:%S.%fZ',       # 2025-05-25T14:00:00.000Z
                '%Y-%m-%dT%H:%M:%S%z',         # 2025-05-25T14:00:00+00:00
                '%Y-%m-%d %H:%M:%S',           # 2025-05-25 14:00:00
                '%Y-%m-%d',                    # 2025-05-25
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(datetime_str, fmt)
                except ValueError:
                    continue
            
            # Fallback : utiliser fromisoformat avec nettoyage
            cleaned = datetime_str.replace('Z', '+00:00')
            return datetime.fromisoformat(cleaned)
            
        except Exception as e:
            logger.error(f"Impossible de parser la date '{datetime_str}': {str(e)}")
            return None
    
    def _extract_email(self, data: Dict[str, Any]) -> Optional[str]:
        """Extrait l'email de différentes sources possibles."""
        # Sources possibles
        email_sources = [
            data.get('email'),
            data.get('attendeeEmail'),
            data.get('answers', {}).get('email'),
            data.get('answers', {}).get('Email'),
            data.get('profile', {}).get('email'),
        ]
        
        # Recherche dans les form fields
        for field in data.get('formFields', []):
            field_name = field.get('name', '').lower()
            if 'email' in field_name:
                email_sources.append(field.get('value'))
        
        # Retourner le premier email valide trouvé
        for email in email_sources:
            if email and '@' in str(email):
                return str(email).strip()
        
        return None
    
    def _extract_name(self, data: Dict[str, Any]) -> Optional[str]:
        """Extrait le nom de différentes sources possibles."""
        # Sources possibles
        name_sources = [
            data.get('name'),
            data.get('attendeeName'),
            data.get('answers', {}).get('name'),
            data.get('answers', {}).get('Name'),
            data.get('profile', {}).get('name'),
        ]
        
        # Construire à partir de firstName + lastName
        first_name = data.get('firstName') or data.get('answers', {}).get('firstName')
        last_name = data.get('lastName') or data.get('answers', {}).get('lastName')
        
        if first_name or last_name:
            name_sources.append(f"{first_name or ''} {last_name or ''}".strip())
        
        # Recherche dans les form fields
        for field in data.get('formFields', []):
            field_name = field.get('name', '').lower()
            if any(x in field_name for x in ['name', 'nom', 'prénom']):
                name_sources.append(field.get('value'))
        
        # Retourner le premier nom valide trouvé
        for name in name_sources:
            if name and str(name).strip():
                return str(name).strip()
        
        return None
    
    def _extract_user_id(self, data: Dict[str, Any]) -> Optional[int]:
        """Extrait l'user_id de différentes sources possibles."""
        user_id_sources = []
        
        # Sources directes
        if data.get('user_id'):
            user_id_sources.append(data.get('user_id'))
        
        # Dans answers
        answers = data.get('answers', {})
        for key in ['user_id', 'User ID', 'USER_ID', 'userId']:
            if answers.get(key):
                user_id_sources.append(answers.get(key))
        
        # Dans formFields
        for field in data.get('formFields', []):
            field_name = field.get('name', '').lower().replace(' ', '_')
            if 'user_id' in field_name or 'userid' in field_name:
                user_id_sources.append(field.get('value'))
        
        # Dans customFields
        for field in data.get('customFields', []):
            if field.get('name', '').lower() in ['user_id', 'userid']:
                user_id_sources.append(field.get('value'))
        
        # Convertir en entier
        for user_id in user_id_sources:
            if user_id:
                try:
                    return int(user_id)
                except (ValueError, TypeError):
                    logger.warning(f"user_id non convertible en entier: {user_id}")
                    continue
        
        return None
    
    def _extract_product_id(self, data: Dict[str, Any]) -> Optional[str]:
        """Extrait le product_id de différentes sources possibles."""
        product_id_sources = []
        
        # Sources directes
        if data.get('product_id'):
            product_id_sources.append(data.get('product_id'))
        
        # Dans answers
        answers = data.get('answers', {})
        for key in ['product_id', 'Product ID', 'PRODUCT_ID', 'productId']:
            if answers.get(key):
                product_id_sources.append(answers.get(key))
        
        # Dans formFields
        for field in data.get('formFields', []):
            field_name = field.get('name', '').lower().replace(' ', '_')
            if 'product_id' in field_name or 'productid' in field_name:
                product_id_sources.append(field.get('value'))
        
        # Retourner le premier product_id valide trouvé
        for product_id in product_id_sources:
            if product_id and str(product_id).strip():
                return str(product_id).strip()
        
        return None
    
    def cancel_booking(self, booking_id: str) -> bool:
        """
        Annule une réservation via l'API YouCanBookMe.
        
        Args:
            booking_id: ID de la réservation à annuler
            
        Returns:
            bool: True si l'annulation a réussi
        """
        if not self.api_key:
            logger.warning("API key YouCanBookMe non configurée - annulation impossible")
            return False
        
        try:
            url = f"{self.base_url}/bookings/{booking_id}/cancel"
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"Réservation {booking_id} annulée avec succès")
                return True
            else:
                logger.error(f"Erreur annulation réservation {booking_id}: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception lors de l'annulation de la réservation {booking_id}: {str(e)}")
            return False
    
    def get_booking_details(self, booking_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les détails d'une réservation via l'API YouCanBookMe.
        
        Args:
            booking_id: ID de la réservation
            
        Returns:
            Dict avec les détails de la réservation ou None
        """
        if not self.api_key:
            logger.warning("API key YouCanBookMe non configurée")
            return None
        
        try:
            url = f"{self.base_url}/bookings/{booking_id}"
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Erreur récupération détails réservation {booking_id}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Exception lors de la récupération des détails {booking_id}: {str(e)}")
            return None
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        Valide la configuration du service YouCanBookMe.
        
        Returns:
            Dict avec le statut de la configuration
        """
        config_status = {
            'api_key_configured': bool(self.api_key),
            'webhook_secret_configured': bool(self.webhook_secret),
            'subdomain': self.subdomain,
            'base_url': self.base_url,
            'api_accessible': False,
            'errors': []
        }
        
        # Test de connectivité API (si clé API configurée)
        if self.api_key:
            try:
                url = f"{self.base_url}/profile"
                headers = {'Authorization': f'Bearer {self.api_key}'}
                response = requests.get(url, headers=headers, timeout=5)
                config_status['api_accessible'] = response.status_code == 200
                
                if response.status_code != 200:
                    config_status['errors'].append(f"API non accessible: {response.status_code}")
                    
            except Exception as e:
                config_status['errors'].append(f"Erreur test API: {str(e)}")
        
        return config_status


# Factory function pour créer le service
def create_youcanbook_service() -> YouCanBookMeService:
    """
    Crée une instance du service YouCanBookMe avec la configuration Flask.
    
    Returns:
        YouCanBookMeService configuré
    """
    api_key = current_app.config.get('YOUCANBOOK_API_KEY')
    webhook_secret = current_app.config.get('YOUCANBOOK_WEBHOOK_SECRET') 
    subdomain = current_app.config.get('YOUCANBOOK_SUBDOMAIN', 'tilto')
    
    return YouCanBookMeService(
        api_key=api_key,
        webhook_secret=webhook_secret, 
        subdomain=subdomain
    )