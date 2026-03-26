import logging
import requests
import json
import re
from typing import Dict, List, Tuple, Optional, Any
from flask import current_app, g

logger = logging.getLogger(__name__)

class AnonymizationClient:
    """Client pour le service d'anonymisation distant avec mode dégradé."""

    def __init__(self, service_url=None, anonymization_enabled=True):
        """
        Initialise le client avec l'URL du service.
        
        Args:
            service_url (str, optional): URL du service d'anonymisation.
                Si None, l'URL sera lue depuis la configuration de l'application.
            anonymization_enabled (bool): Active ou désactive l'anonymisation.
        """
        self.service_url = service_url
        self.anonymization_enabled = anonymization_enabled
        self.replacement_cache = {}
        self.timeout = 30  # Timeout en secondes
        self.failure_count = 0
        self.max_failures = 5  # Nombre d'échecs consécutifs avant mode dégradé temporaire
        self.last_failure_time = 0
        self.retry_interval = 300  # 5 minutes entre les tentatives après échecs
        
    def _get_service_url(self):
        """Obtient l'URL du service depuis la configuration si nécessaire."""
        if self.service_url:
            return self.service_url
            
        # Récupérer depuis la configuration de l'application
        try:
            self.service_url = current_app.config.get('ANONYMIZATION_SERVICE_URL')
            if not self.service_url:
                logger.warning("URL du service d'anonymisation non configurée. Utilisation de l'URL par défaut.")
                self.service_url = "https://anonymization-service-[ID_UNIQUE].run.app"
            return self.service_url
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de l'URL du service: {str(e)}")
            # URL par défaut en cas d'erreur
            return "https://anonymization-service-[ID_UNIQUE].run.app"
    
    def _should_use_service(self):
        """Détermine si le service d'anonymisation doit être utilisé."""
        if not self.anonymization_enabled:
            return False
            
        # Si trop d'échecs consécutifs, passer en mode dégradé temporaire
        import time
        current_time = time.time()
        if self.failure_count >= self.max_failures:
            # Vérifier si on peut réessayer
            if current_time - self.last_failure_time > self.retry_interval:
                logger.info("Tentative de réutilisation du service d'anonymisation après période de backoff")
                self.failure_count = 0
                return True
            else:
                return False
                
        return True
    
    def _handle_service_failure(self):
        """Gère un échec du service d'anonymisation."""
        import time
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.max_failures:
            logger.warning(f"Service d'anonymisation indisponible après {self.failure_count} échecs. Passage en mode dégradé.")
        else:
            logger.warning(f"Échec du service d'anonymisation ({self.failure_count}/{self.max_failures})")
    
    def anonymize_text(self, text: str, request_id: str = None) -> str:
        """
        Anonymise un texte en appelant le service d'anonymisation.
        Retourne le texte original si le service est désactivé ou indisponible.
        
        Args:
            text (str): Le texte à anonymiser
            request_id (str, optional): Identifiant de la requête pour le logging
            
        Returns:
            str: Le texte anonymisé ou le texte original en mode dégradé
        """
        if not text:
            return text
            
        # Vérifier si on doit utiliser le service
        if not self._should_use_service():
            logger.info(f"[Request ID: {request_id}] Mode dégradé: pas d'anonymisation")
            return text
            
        try:
            service_url = self._get_service_url()
            endpoint = f"{service_url}/anonymize"
            
            logger.info(f"[Request ID: {request_id}] Appel au service d'anonymisation: {endpoint}")
            
            response = requests.post(
                endpoint,
                json={"text": text, "request_id": request_id},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(f"[Request ID: {request_id}] Erreur du service d'anonymisation: {response.status_code} - {response.text}")
                self._handle_service_failure()
                return text
                
            result = response.json()
            
            # Réinitialiser le compteur d'échecs
            self.failure_count = 0
            
            # Stocker le cache de remplacement pour une utilisation ultérieure
            if "replacements" in result:
                self.replacement_cache.update(result["replacements"])
                
            return result["anonymized"]
            
        except requests.RequestException as e:
            logger.error(f"[Request ID: {request_id}] Erreur de connexion au service d'anonymisation: {str(e)}")
            self._handle_service_failure()
            return text
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Erreur inattendue lors de l'anonymisation: {str(e)}")
            return text
    
    def anonymize_prompt_data(self, prompt_data: List[Dict], request_id: str = None) -> List[Dict]:
        """
        Anonymise uniquement les réponses dans les données de prompt,
        en gardant les questions intactes.
        
        Args:
            prompt_data (List[Dict]): Liste de dictionnaires avec questions/réponses
            request_id (str, optional): Identifiant de la requête pour le logging
            
        Returns:
            List[Dict]: Les données de prompt avec réponses anonymisées
        """
        if not prompt_data:
            return prompt_data
            
        # Vérifier si on doit utiliser le service
        if not self._should_use_service():
            logger.info(f"[Request ID: {request_id}] Mode dégradé: pas d'anonymisation des données de prompt")
            return prompt_data
            
        try:
            service_url = self._get_service_url()
            endpoint = f"{service_url}/anonymize-prompt-data"
            
            logger.info(f"[Request ID: {request_id}] Appel au service d'anonymisation pour les données de prompt: {endpoint}")
            
            response = requests.post(
                endpoint,
                json={"prompt_data": prompt_data, "request_id": request_id},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(f"[Request ID: {request_id}] Erreur du service d'anonymisation: {response.status_code} - {response.text}")
                self._handle_service_failure()
                return prompt_data
                
            result = response.json()
            
            # Réinitialiser le compteur d'échecs
            self.failure_count = 0
            
            # Stocker le cache de remplacement pour une utilisation ultérieure
            if "replacements" in result:
                self.replacement_cache.update(result["replacements"])
                
            return result["anonymized"]
            
        except requests.RequestException as e:
            logger.error(f"[Request ID: {request_id}] Erreur de connexion au service d'anonymisation: {str(e)}")
            self._handle_service_failure()
            return prompt_data
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Erreur inattendue lors de l'anonymisation: {str(e)}")
            return prompt_data
    
    def test_anonymization_logging(self, text: str, request_id: str = None) -> Tuple[str, str]:
        """
        Teste l'anonymisation d'un texte et retourne l'original et l'anonymisé pour comparaison.
        
        Args:
            text (str): Le texte à anonymiser
            request_id (str, optional): Identifiant de la requête pour le logging
            
        Returns:
            Tuple[str, str]: (texte original, texte anonymisé)
        """
        if request_id is None:
            request_id = "test-anonymization"
            
        anonymized_text = self.anonymize_text(text, request_id)
        return text, anonymized_text
    
    def denonymize_claude_response(self, response_text: str, request_id: str = None, stored_cache: Dict = None) -> str:
        """
        Dénonymise une réponse de Claude contenant des marqueurs d'anonymisation.
        
        Args:
            response_text (str): La réponse à dénonymiser
            request_id (str, optional): Identifiant de la requête pour le logging
            stored_cache (Dict, optional): Cache de remplacement stocké
            
        Returns:
            str: La réponse dénonymisée
        """
        if not response_text:
            return response_text
            
        # Vérifier s'il y a des marqueurs à dénonymiser
        if not re.search(r'\[(PER|LOC|ORG|DATE|EMAIL|PHONE|MISC)_\d+\]', response_text):
            return response_text
            
        try:
            # Utiliser le cache stocké ou le cache en mémoire
            replacement_cache = stored_cache if stored_cache else self.replacement_cache
            
            if not replacement_cache:
                logger.warning(f"[Request ID: {request_id}] Aucun cache de remplacement disponible pour la dénonymisation.")
                return response_text
                
            # Inverser le dictionnaire de remplacement
            inverted_cache = {}
            for key, value in replacement_cache.items():
                # Clé est au format "TYPE:valeur_originale"
                original_value = key.split(':', 1)[1]
                inverted_cache[value] = original_value
            
            # Pattern pour trouver les tags anonymisés
            pattern = r'\[(PER|LOC|ORG|DATE|EMAIL|PHONE|MISC)_(\d+)\]'
            
            # Remplacer les tags par leurs valeurs d'origine
            denonymized_text = response_text
            for match in re.finditer(pattern, response_text):
                tag = match.group(0)
                if tag in inverted_cache:
                    denonymized_text = denonymized_text.replace(tag, inverted_cache[tag])
            
            return denonymized_text
            
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Erreur lors de la dénonymisation: {str(e)}")
            return response_text