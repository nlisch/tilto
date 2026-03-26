# services/audio_capsule_service.py
from google.cloud import storage
from datetime import datetime, timedelta
import uuid
import logging
from flask import current_app
import os
import time

logger = logging.getLogger(__name__)

from google.oauth2 import service_account

class AudioCapsuleService:

    def __init__(self):
        try:
            # Récupérer la clé du compte de service depuis App Config
            service_account_key_json = current_app.config.get('GCP_SERVICE_ACCOUNT')
            
            # Log sécurisé du type sans exposer le contenu
            logger.info(f"Type de service_account_key_json: {type(service_account_key_json)}")
            
            if service_account_key_json:
                logger.info("Clé de compte de service trouvée dans App Config")
                
                # Si c'est une chaîne JSON, convertissez-la en dictionnaire
                if isinstance(service_account_key_json, str):
                    try:
                        import json
                        service_account_key_dict = json.loads(service_account_key_json)
                        logger.info("Conversion réussie de la chaîne JSON en dictionnaire")
                    except json.JSONDecodeError as e:
                        logger.error(f"Erreur lors du décodage JSON: {e}")
                        # Ne pas logger le contenu de la chaîne, même partiellement
                        logger.error("Impossible d'analyser la chaîne JSON")
                        raise
                else:
                    service_account_key_dict = service_account_key_json
                    logger.info("La clé est déjà au format dictionnaire")
                
                # Vérifier la présence des clés essentielles de façon sécurisée
                required_keys = ['type', 'private_key', 'client_email', 'project_id']
                missing_keys = [key for key in required_keys if key not in service_account_key_dict]
                
                if missing_keys:
                    logger.error(f"Clés manquantes dans la configuration du compte de service: {missing_keys}")
                    # Logger uniquement les noms des clés, pas leur contenu
                    present_keys = [key for key in service_account_key_dict.keys() if key not in ['private_key', 'private_key_id']]
                    logger.error(f"Clés non sensibles présentes: {present_keys}")
                else:
                    logger.info("Toutes les clés requises sont présentes")
                    # Vérifier que la private_key commence bien par le bon format sans exposer son contenu
                    has_valid_key = False
                    if 'private_key' in service_account_key_dict:
                        private_key = service_account_key_dict.get('private_key', '')
                        has_valid_key = private_key and private_key.startswith('-----BEGIN PRIVATE KEY-----')
                    
                    if has_valid_key:
                        logger.info("Format de la private_key valide")
                    else:
                        logger.error("Format de la private_key invalide ou absent")
                
                # Créer les identifiants
                try:
                    credentials = service_account.Credentials.from_service_account_info(
                        service_account_key_dict,
                        scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                    )
                    logger.info("Credentials créés avec succès")
                    
                    # Logger de façon sécurisée l'email du compte de service sans exposer d'autres informations
                    if hasattr(credentials, 'service_account_email'):
                        email = credentials.service_account_email
                        masked_email = email[:3] + "..." + email[email.find('@'):]
                        logger.info(f"Utilisation du compte de service: {masked_email}")
                    
                    self.storage_client = storage.Client(credentials=credentials)
                    logger.info("Client de stockage initialisé avec les credentials personnalisés")
                except Exception as cred_error:
                    # Éviter de logger l'erreur complète qui pourrait contenir des informations sensibles
                    logger.error(f"Erreur lors de la création des credentials: {type(cred_error).__name__}")
                    raise
                
                # Déterminer l'environnement
                self.env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
                
                # Initialisation des buckets avec différents noms selon l'environnement
                if self.env == 'development':
                    # Buckets de développement
                    self.bucket_name = os.environ.get('AUDIO_CAPSULES_BUCKET', 'capsules_audio_dev')
                    self.feedback_bucket_name = os.environ.get('AUDIO_FEEDBACKS_BUCKET', 'capsules_audio_feedbacks_dev')
                else:
                    # Buckets de production
                    self.bucket_name = os.environ.get('AUDIO_CAPSULES_BUCKET', 'capsules_audio')
                    self.feedback_bucket_name = os.environ.get('AUDIO_FEEDBACKS_BUCKET', 'capsules_audio_feedbacks')
                
                self.bucket = self.storage_client.bucket(self.bucket_name)
                logger.info(f"AudioCapsuleService initialized with bucket: {self.bucket_name} for environment: {self.env}")
                
            else:
                # Chercher un fichier de clé comme fallback
                key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
                logger.info(f"Aucune clé dans App Config, recherche du fichier: {key_path}")
                
                if key_path and os.path.exists(key_path):
                    try:
                        logger.info(f"Fichier de clé trouvé: {key_path}")
                        credentials = service_account.Credentials.from_service_account_file(
                            key_path, 
                            scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                        )
                        self.storage_client = storage.Client(credentials=credentials)
                        logger.info(f"Client de stockage initialisé avec le fichier de clé: {key_path}")
                    except Exception as key_error:
                        logger.error(f"Erreur lors de l'utilisation du fichier de clé: {type(key_error).__name__}")
                        raise
                else:
                    # Tentative avec les identifiants par défaut
                    logger.warning("Aucune clé trouvée, tentative avec les identifiants par défaut")
                    try:
                        self.storage_client = storage.Client()
                        logger.info("Client de stockage initialisé avec les identifiants par défaut")
                        
                        # Vérifier le type de credentials utilisé
                        if hasattr(self.storage_client, '_credentials'):
                            cred_type = type(self.storage_client._credentials).__name__
                            logger.info(f"Type de credentials par défaut: {cred_type}")
                            
                            # Vérifier si les credentials ont une clé privée
                            has_private_key = hasattr(self.storage_client._credentials, '_signing_credentials')
                            logger.info(f"Les credentials possèdent une clé privée: {has_private_key}")
                    except Exception as default_error:
                        logger.error(f"Erreur lors de l'initialisation avec les identifiants par défaut: {type(default_error).__name__}")
                        raise
                
                # Déterminer l'environnement
                self.env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
                
                # Initialisation des buckets avec différents noms selon l'environnement
                if self.env == 'development':
                    # Buckets de développement
                    self.bucket_name = os.environ.get('AUDIO_CAPSULES_BUCKET', 'capsules_audio_dev')
                    self.feedback_bucket_name = os.environ.get('AUDIO_FEEDBACKS_BUCKET', 'capsules_audio_feedbacks_dev')
                else:
                    # Buckets de production
                    self.bucket_name = os.environ.get('AUDIO_CAPSULES_BUCKET', 'capsules_audio')
                    self.feedback_bucket_name = os.environ.get('AUDIO_FEEDBACKS_BUCKET', 'capsules_audio_feedbacks')
                
                self.bucket = self.storage_client.bucket(self.bucket_name)
                logger.info(f"AudioCapsuleService initialized with bucket: {self.bucket_name} for environment: {self.env}")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de AudioCapsuleService: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
            

    def generate_signed_url(self, blob_name, duration_minutes=30, user_ip=None):
        """
        Génère une URL signée pour accéder à un fichier audio
        
        Args:
            blob_name (str): Nom du fichier dans le bucket
            duration_minutes (int): Durée de validité de l'URL en minutes
            user_ip (str, optional): Adresse IP de l'utilisateur pour restreindre l'accès
            
        Returns:
            str: URL signée
        """
        try:
            blob = self.bucket.blob(blob_name)
            
            if not blob.exists():
                logger.error(f"Le fichier {blob_name} n'existe pas dans le bucket {self.bucket_name}")
                return None
                
            # Configuration de l'URL signée
            expiration = datetime.now() + timedelta(minutes=duration_minutes)
            
            # Options de l'URL signée - version corrigée sans response_headers
            signing_options = {
                'version': 'v4',
                'expiration': expiration,
                'method': 'GET',
                'response_disposition': f'inline; filename="{os.path.basename(blob_name)}"'
            }
            
            # Note: La restriction par IP n'est pas directement supportée avec response_headers
            # Si vous avez besoin de cette fonctionnalité, vous devrez l'implémenter autrement
            # Par exemple en vérifiant l'IP à l'accès au fichier
            
            # Générer l'URL signée
            signed_url = blob.generate_signed_url(**signing_options)
            
            logger.info(f"URL signée générée pour {blob_name} (expire le {expiration})")
            return signed_url
            
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'URL signée pour {blob_name}: {e}")
            return None
    
    def upload_audio_file(self, file_content, original_filename):
        """
        Téléverse un fichier audio dans le bucket et retourne son nom
        
        Args:
            file_content: Contenu du fichier
            original_filename: Nom original du fichier sécurisé
            
        Returns:
            str: Nom du fichier dans le bucket
        """
        try:
            # Générer un nom de fichier unique
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_id = str(uuid.uuid4())[:8]
            extension = os.path.splitext(original_filename)[1]
            storage_filename = f"{timestamp}_{unique_id}{extension}"
            
            # Créer le blob et téléverser le fichier
            blob = self.bucket.blob(storage_filename)
            
            # Si file_content est un objet file-like (comme request.files['file'])
            if hasattr(file_content, 'read'):
                blob.upload_from_file(file_content)
            else:
                # Si c'est des données binaires brutes
                blob.upload_from_string(file_content)
            
            logger.info(f"Fichier audio téléversé avec succès: {storage_filename}")
            return storage_filename
        except Exception as e:
            logger.error(f"Erreur lors du téléversement du fichier audio: {e}")
            raise
    
    # Dans audio_capsule_service.py, méthode delete_audio_file
    def delete_audio_file(self, filename):
        """
        Supprime un fichier audio du bucket
        
        Args:
            filename (str): Nom du fichier à supprimer
            
        Returns:
            bool: True si le fichier a été supprimé, False sinon
        """
        try:
            blob = self.bucket.blob(filename)
            # Supprimer la vérification d'existence qui ne fonctionne pas correctement
            # if not blob.exists():
            #     logger.warning(f"Le fichier {filename} n'existe pas dans le bucket")
            #     return False
            
            # Tenter la suppression directement
            blob.delete()
            logger.info(f"Fichier audio supprimé avec succès: {filename}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du fichier audio {filename}: {e}")
            return False

    # De même pour delete_feedback_file
    def delete_feedback_file(self, filename):
        """
        Supprime un fichier de feedback audio
        
        Args:
            filename (str): Nom du fichier à supprimer
            
        Returns:
            bool: True si le fichier a été supprimé, False sinon
        """
        try:
            feedback_bucket = self.get_feedback_bucket()
            blob = feedback_bucket.blob(filename)
            
            # Supprimer cette vérification
            # if not blob.exists():
            #     logger.warning(f"Le fichier de feedback {filename} n'existe pas dans le bucket")
            #     return False
                
            blob.delete()
            logger.info(f"Fichier de feedback supprimé avec succès: {filename}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du fichier de feedback {filename}: {e}")
            return False
    
    def generate_user_token(self):
        """
        Génère un token unique pour l'accès utilisateur
        
        Returns:
            str: Token d'accès unique
        """
        timestamp = int(time.time())
        random_component = str(uuid.uuid4())
        # Créer un token unique combinant timestamp et UUID
        token = f"{timestamp}_{random_component}"
        return token
    
    def list_audio_files(self, prefix=None):
        """
        Liste les fichiers audio disponibles dans le bucket
        
        Args:
            prefix (str, optional): Préfixe pour filtrer les fichiers
            
        Returns:
            list: Liste des fichiers audio
        """
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
            return [
                {
                    'name': blob.name,
                    'size': blob.size,
                    'updated': blob.updated,
                    'content_type': blob.content_type
                } for blob in blobs if blob.content_type and 'audio' in blob.content_type
            ]
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des fichiers audio: {e}")
            return []
            
    def upload_feedback_audio(self, audio_file, event_id):
        """
        Téléverse un fichier audio de feedback dans le bucket Cloud Storage
        
        Args:
            audio_file: Objet fichier contenant l'audio du feedback
            event_id: ID de l'événement d'écoute associé au feedback
            
        Returns:
            str: Nom du fichier dans le bucket ou None en cas d'erreur
        """
        try:
            # Utiliser le bucket spécifique pour les feedbacks audio selon l'environnement
            feedback_bucket = self.get_feedback_bucket()
            
            # Générer un nom de fichier unique
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"feedback_{event_id}_{timestamp}.webm"
            
            # Créer le blob et téléverser le fichier
            blob = feedback_bucket.blob(filename)
            
            # Téléverser le fichier
            blob.upload_from_file(audio_file)
            
            # Essayer de définir les métadonnées, mais ne pas échouer si ça ne fonctionne pas
            try:
                blob.metadata = {
                    'event_id': str(event_id),
                    'uploaded_at': timestamp,
                    'content_type': 'audio/webm'
                }
                blob.patch()
            except Exception as metadata_error:
                # Logger l'erreur mais continuer
                logger.warning(f"Impossible de mettre à jour les métadonnées du feedback: {metadata_error}")
                # Le téléchargement a réussi même si les métadonnées n'ont pas pu être mises à jour
            
            logger.info(f"Feedback audio téléversé avec succès: {filename} dans le bucket {feedback_bucket.name}")
            return filename
            
        except Exception as e:
            logger.error(f"Erreur lors du téléversement du feedback audio: {e}")
            return None

    def get_feedback_bucket(self):
        """
        Récupère ou crée le bucket pour les feedbacks audio
        
        Returns:
            Bucket: Objet bucket pour les feedbacks audio
        """
        try:
            feedback_bucket = self.storage_client.bucket(self.feedback_bucket_name)
            if not feedback_bucket.exists():
                logger.info(f"Création du bucket {self.feedback_bucket_name}")
                try:
                    feedback_bucket = self.storage_client.create_bucket(
                        self.feedback_bucket_name,
                        location="europe-west1"  # Choisissez la région appropriée
                    )
                except Exception as bucket_error:
                    logger.error(f"Erreur lors de la création du bucket: {bucket_error}")
                    # Fallback sur le bucket principal
                    feedback_bucket = self.bucket
            logger.info(f"Utilisation du bucket feedback: {self.feedback_bucket_name} pour l'environnement: {self.env}")
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du bucket de feedback: {e}")
            feedback_bucket = self.bucket
            
        return feedback_bucket

    def generate_signed_url_for_feedback(self, filename, duration_minutes=3):
        """
        Génère une URL signée pour accéder à un fichier audio de feedback
        
        Args:
            filename (str): Nom du fichier dans le bucket
            duration_minutes (int): Durée de validité de l'URL en minutes
            
        Returns:
            str: URL signée
        """
        try:
            feedback_bucket = self.get_feedback_bucket()
            blob = feedback_bucket.blob(filename)
            
            if not blob.exists():
                logger.error(f"Le fichier de feedback {filename} n'existe pas dans le bucket {feedback_bucket.name}")
                return None
                
            # Configuration de l'URL signée
            expiration = datetime.now() + timedelta(minutes=duration_minutes)
            
            # Options de l'URL signée
            signing_options = {
                'version': 'v4',
                'expiration': expiration,
                'method': 'GET',
                'response_disposition': f'inline; filename="{os.path.basename(filename)}"'
            }
            
            # Générer l'URL signée
            signed_url = blob.generate_signed_url(**signing_options)
            
            logger.info(f"URL signée générée pour le feedback {filename} (expire le {expiration})")
            return signed_url
                
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'URL signée pour le feedback {filename}: {e}")
            return None

    def list_feedback_files(self, event_id=None):
        """
        Liste les fichiers de feedback audio disponibles
        
        Args:
            event_id (int, optional): Filtrer par ID d'événement
            
        Returns:
            list: Liste des fichiers de feedback audio
        """
        try:
            feedback_bucket = self.get_feedback_bucket()
            
            # Préfixe pour filtrer par event_id si fourni
            prefix = f"feedback_{event_id}_" if event_id else "feedback_"
            
            blobs = feedback_bucket.list_blobs(prefix=prefix)
            return [
                {
                    'name': blob.name,
                    'size': blob.size,
                    'updated': blob.updated,
                    'content_type': blob.content_type,
                    'metadata': blob.metadata,
                    'event_id': blob.metadata.get('event_id') if blob.metadata else None
                } for blob in blobs if 'audio' in (blob.content_type or '')
            ]
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des fichiers de feedback: {e}")
            return []