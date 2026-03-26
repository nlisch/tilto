import tempfile
import os
import logging
import requests
from flask import current_app
from datetime import datetime,timedelta
import uuid
import json
from google.cloud import storage
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

class AudioService:
    @staticmethod
    def transcribe_with_whisper(audio_file):
        """
        Transcrit un fichier audio en utilisant l'API Whisper d'OpenAI
        """
        try:
            # Créer un fichier temporaire
            with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_file:
                temp_path = temp_file.name
                # Enregistrer le fichier audio
                audio_file.save(temp_path)
                logger.info(f"Fichier audio temporaire créé à {temp_path}")
                # Obtenir la clé API OpenAI
                api_key = current_app.config.get('OPENAI_API_KEY')
                if not api_key:
                    raise ValueError("Clé API OpenAI non configurée")
                # Préparer la requête API
                headers = {
                    "Authorization": f"Bearer {api_key}"
                }
                # Envoyer le fichier à l'API Whisper
                with open(temp_path, 'rb') as audio:
                    files = {
                        'file': (os.path.basename(temp_path), audio, 'audio/webm'),
                        'model': (None, 'whisper-1'),
                        'language': (None, 'fr'),
                        'response_format': (None, 'json')
                    }
                    response = requests.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers=headers,
                        files=files,
                        timeout=60
                    )
                    response.raise_for_status()
                    result = response.json()
                    transcript = result.get('text', '')
                    logger.info(f"Transcription réussie: {transcript[:50]}...")
                return {"success": True, "transcript": transcript}
        except Exception as e:
            logger.error(f"Erreur lors de la transcription: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}
        finally:
            # Nettoyage des fichiers temporaires
            try:
                if 'temp_path' in locals():
                    os.unlink(temp_path)
            except Exception as cleanup_error:
                logger.warning(f"Erreur lors du nettoyage des fichiers temporaires: {cleanup_error}")

    @staticmethod
    def save_quiz_audio_to_cloud(audio_blob, quiz_id, question_id, user_id, file_format=None):
        """
        Sauvegarde un fichier audio du quiz dans le cloud storage
        Supporte WebM (Chrome/Firefox) et MP4 (Safari iOS)
        """
        try:
            
            # Configuration des buckets selon l'environnement
            env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
            
            if env == 'development':
                bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_dev')
            else:
                bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_prod')
            
            # Initialisation du client storage avec les mêmes credentials que AudioCapsuleService
            service_account_key_json = current_app.config.get('GCP_SERVICE_ACCOUNT')
            
            if service_account_key_json:
                if isinstance(service_account_key_json, str):
                    
                    service_account_key_dict = json.loads(service_account_key_json)
                else:
                    service_account_key_dict = service_account_key_json
                
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_key_dict,
                    scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                )
                client = storage.Client(credentials=credentials)
            else:
                # Fallback sur les credentials par défaut
                key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
                if key_path and os.path.exists(key_path):
                    credentials = service_account.Credentials.from_service_account_file(
                        key_path, 
                        scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                    )
                    client = storage.Client(credentials=credentials)
                else:
                    client = storage.Client()
            
            bucket = client.bucket(bucket_name)
            
            # MODIFICATION: Déterminer le format de fichier
            if file_format and file_format in ['.webm', '.mp4']:
                file_extension = file_format
            else:
                file_extension = '.webm'  # Par défaut
            
            # Générer un nom de fichier unique et descriptif avec la bonne extension
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{quiz_id}/user_{user_id}/q{question_id}_{timestamp}_{unique_id}{file_extension}"
            
            # Créer le blob et uploader
            blob = bucket.blob(filename)
            
            # MODIFICATION: Utiliser le bon content_type selon le format
            content_type = AudioService.get_mime_type(file_extension)
            
            # Upload du fichier avec le bon type MIME
            blob.upload_from_string(
                audio_blob,
                content_type=content_type
            )
            
            # Ajouter des métadonnées
            try:
                blob.metadata = {
                    'quiz_id': str(quiz_id),
                    'question_id': str(question_id),
                    'user_id': str(user_id),
                    'uploaded_at': timestamp,
                    'environment': env,
                    'format': file_extension[1:]  # webm ou mp4
                }
                blob.patch()
            except Exception as metadata_error:
                logger.warning(f"Impossible de mettre à jour les métadonnées: {metadata_error}")
            
            # Générer l'URL du fichier
            audio_url = f"gs://{bucket_name}/{filename}"
            
            logger.info(f"Audio quiz sauvegardé avec succès: {filename} ({file_extension}) dans {bucket_name} (env: {env})")
            return {
                'success': True,
                'url': audio_url,
                'filename': filename,
                'bucket': bucket_name,
                'environment': env,
                'format': file_extension[1:]
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde audio quiz: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    @staticmethod
    def process_quiz_audio_batch(audio_data_list, quiz_id, user_id):
        """
        Traite un lot d'audios du quiz et retourne les URLs
        """
        results = {}
        
        for audio_data in audio_data_list:
            question_id = audio_data.get('question_id')
            audio_blob = audio_data.get('blob')
            
            if not question_id or not audio_blob:
                continue
                
            result = AudioService.save_quiz_audio_to_cloud(
                audio_blob, quiz_id, question_id, user_id
            )
            
            if result['success']:
                results[question_id] = {
                    'url': result['url'],
                    'filename': result['filename'],
                    'environment': result['environment']
                }
            else:
                logger.error(f"Échec sauvegarde audio Q{question_id}: {result['error']}")
                results[question_id] = None
        
        return results

    @staticmethod
    def generate_signed_url_for_quiz_audio(filename, duration_minutes=30):
        """
        Génère une URL signée pour accéder à un fichier audio du quiz
        """
        try:
            
            # Configuration des buckets selon l'environnement
            env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
            
            if env == 'development':
                bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_dev')
            else:
                bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_prod')
            
            # Initialisation du client (même logique que save_quiz_audio_to_cloud)
            service_account_key_json = current_app.config.get('GCP_SERVICE_ACCOUNT')
            
            if service_account_key_json:
                if isinstance(service_account_key_json, str):
                    service_account_key_dict = json.loads(service_account_key_json)
                else:
                    service_account_key_dict = service_account_key_json
                
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_key_dict,
                    scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                )
                client = storage.Client(credentials=credentials)
            else:
                key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
                if key_path and os.path.exists(key_path):
                    credentials = service_account.Credentials.from_service_account_file(
                        key_path, 
                        scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                    )
                    client = storage.Client(credentials=credentials)
                else:
                    client = storage.Client()
            
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(filename)
            
            if not blob.exists():
                logger.error(f"Le fichier audio quiz {filename} n'existe pas dans {bucket_name}")
                return None
            
            # Configuration de l'URL signée
            expiration = datetime.now() + timedelta(minutes=duration_minutes)
            
            signing_options = {
                'version': 'v4',
                'expiration': expiration,
                'method': 'GET',
                'response_disposition': f'inline; filename="{os.path.basename(filename)}"'
            }
            
            signed_url = blob.generate_signed_url(**signing_options)
            
            logger.info(f"URL signée générée pour audio quiz {filename} (expire le {expiration})")
            return signed_url
            
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'URL signée pour audio quiz {filename}: {e}")
            return None

    @staticmethod
    def delete_quiz_audio_file(filename):
        """
        Supprime un fichier audio du quiz du cloud storage
        """
        try:
            
            # Configuration des buckets selon l'environnement
            env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
            
            if env == 'development':
                bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_dev')
            else:
                bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_prod')
            
            # Initialisation du client (même logique)
            service_account_key_json = current_app.config.get('GCP_SERVICE_ACCOUNT')
            
            if service_account_key_json:
                if isinstance(service_account_key_json, str):
                    service_account_key_dict = json.loads(service_account_key_json)
                else:
                    service_account_key_dict = service_account_key_json
                
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_key_dict,
                    scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                )
                client = storage.Client(credentials=credentials)
            else:
                key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
                if key_path and os.path.exists(key_path):
                    credentials = service_account.Credentials.from_service_account_file(
                        key_path, 
                        scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                    )
                    client = storage.Client(credentials=credentials)
                else:
                    client = storage.Client()
            
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(filename)
            
            # Supprimer directement sans vérifier l'existence (comme AudioCapsuleService)
            blob.delete()
            logger.info(f"Fichier audio quiz supprimé avec succès: {filename} dans {bucket_name}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du fichier audio quiz {filename}: {e}")
            return False

    @staticmethod
    def transcribe_quiz_audio_from_gcs(gcs_path):
        """
        Transcrit un fichier audio stocké dans Google Cloud Storage avec gestion des limites de taux
        """
        try:
            # Télécharger temporairement le fichier depuis GCS
            from google.cloud import storage
            from google.oauth2 import service_account
            import json
            import tempfile
            import os
            import requests
            import time
            
            # Configuration du client storage (réutiliser la logique existante)
            service_account_key_json = current_app.config.get('GCP_SERVICE_ACCOUNT')
            
            if service_account_key_json:
                if isinstance(service_account_key_json, str):
                    service_account_key_dict = json.loads(service_account_key_json)
                else:
                    service_account_key_dict = service_account_key_json
                
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_key_dict,
                    scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
                )
                client = storage.Client(credentials=credentials)
            else:
                client = storage.Client()
            
            # Extraire le bucket et le nom du fichier depuis le chemin GCS
            if gcs_path.startswith('gs://'):
                path_parts = gcs_path[5:].split('/', 1)
                bucket_name = path_parts[0]
                file_path = path_parts[1]
            else:
                logger.error(f"Format de chemin GCS invalide: {gcs_path}")
                return {"success": False, "error": "Format de chemin invalide"}
            
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            if not blob.exists():
                logger.error(f"Le fichier {gcs_path} n'existe pas")
                return {"success": False, "error": "Fichier introuvable"}
            
            # Télécharger le fichier dans un fichier temporaire
            with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_file:
                temp_path = temp_file.name
                blob.download_to_filename(temp_path)
                
            logger.info(f"Fichier téléchargé temporairement: {temp_path}")
            
            try:
                # Utiliser la méthode existante pour transcrire avec retry
                api_key = current_app.config.get('OPENAI_API_KEY')
                if not api_key:
                    raise ValueError("Clé API OpenAI non configurée")
                
                headers = {
                    "Authorization": f"Bearer {api_key}"
                }
                
                # Retry avec backoff exponentiel
                max_retries = 3
                base_delay = 1  # 1 seconde
                
                for attempt in range(max_retries):
                    try:
                        # Envoyer le fichier à l'API Whisper
                        with open(temp_path, 'rb') as audio:
                            files = {
                                'file': (os.path.basename(temp_path), audio, 'audio/webm'),
                                'model': (None, 'whisper-1'),
                                'language': (None, 'fr'),
                                'response_format': (None, 'json')
                            }
                            
                            response = requests.post(
                                "https://api.openai.com/v1/audio/transcriptions",
                                headers=headers,
                                files=files,
                                timeout=60
                            )
                            
                            # Si succès, retourner le résultat
                            if response.status_code == 200:
                                result = response.json()
                                transcript = result.get('text', '')
                                logger.info(f"Transcription réussie pour {gcs_path}: {transcript[:50]}...")
                                return {"success": True, "transcript": transcript}
                            
                            # Si erreur 429 (Too Many Requests), faire un retry
                            elif response.status_code == 429:
                                if attempt < max_retries - 1:  # Pas le dernier essai
                                    delay = base_delay * (2 ** attempt)  # Backoff exponentiel
                                    logger.warning(f"Rate limit atteint (429), retry dans {delay}s (tentative {attempt + 1}/{max_retries})")
                                    time.sleep(delay)
                                    continue
                                else:
                                    logger.error(f"Rate limit atteint après {max_retries} tentatives")
                                    return {"success": False, "error": "Limite de taux OpenAI dépassée. Veuillez réessayer dans quelques minutes."}
                            
                            # Autres erreurs HTTP
                            else:
                                response.raise_for_status()
                                
                    except requests.exceptions.RequestException as req_error:
                        if attempt < max_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"Erreur requête ({str(req_error)}), retry dans {delay}s (tentative {attempt + 1}/{max_retries})")
                            time.sleep(delay)
                            continue
                        else:
                            raise req_error
                            
            finally:
                # Nettoyer le fichier temporaire
                try:
                    os.unlink(temp_path)
                except Exception as cleanup_error:
                    logger.warning(f"Erreur lors du nettoyage: {cleanup_error}")
                    
        except Exception as e:
            logger.error(f"Erreur lors de la transcription depuis GCS {gcs_path}: {str(e)}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def detect_audio_format(audio_file_or_blob):
        """Détecte le format audio (webm ou mp4)"""
        if hasattr(audio_file_or_blob, 'content_type'):
            return '.mp4' if 'mp4' in audio_file_or_blob.content_type else '.webm'
        return '.webm'  # Par défaut

    @staticmethod
    def get_mime_type(extension):
        """Retourne le type MIME selon l'extension"""
        return 'audio/mp4' if extension == '.mp4' else 'audio/webm'