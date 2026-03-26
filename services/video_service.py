# services/video_service.py
from google.cloud import storage
import uuid
import logging
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app

logger = logging.getLogger(__name__)

class VideoService:
    def __init__(self):
        try:
            self.storage_client = storage.Client()
            self.bucket = self.storage_client.bucket(current_app.config['STORAGE_BUCKET'])
            self.cdn_url = current_app.config['CDN_URL']
            self.env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
            self.video_config = current_app.config['VIDEOS']
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de VideoService: {e}")
            raise

    def generate_public_url(self, blob_path):
        """Génère une URL publique stable via le CDN"""
        return f"{self.cdn_url}/{blob_path}"

    def validate_video(self, video_file):
        """Valide la taille et le type du fichier vidéo"""
        try:
            # Vérifier la taille du fichier
            video_file.seek(0, 2)  # Aller à la fin du fichier
            file_size = video_file.tell()
            video_file.seek(0)  # Revenir au début
            
            max_size = self.video_config['MAX_SIZE_MB'] * 1024 * 1024  # Convertir MB en bytes
            if file_size > max_size:
                raise Exception(f"La vidéo dépasse la taille maximale autorisée de {self.video_config['MAX_SIZE_MB']} MB")
            
            logger.info(f"Vidéo validée: {file_size / (1024 * 1024):.2f} MB")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la validation de la vidéo: {e}")
            raise

    def generate_filename(self, original_filename):
        """Génère un nom de fichier unique avec date"""
        try:
            date_prefix = datetime.now().strftime('%Y/%m')
            filename = secure_filename(original_filename)
            unique_id = str(uuid.uuid4())[:8]
            # Conserver l'extension originale
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, 'mp4')
            return f"{date_prefix}/{unique_id}_{name}.{ext.lower()}"
        except Exception as e:
            logger.error(f"Erreur lors de la génération du nom de fichier: {e}")
            raise

    def list_pending_videos(self):
        """Liste les vidéos en attente de validation"""
        try:
            blobs = self.bucket.list_blobs(prefix='videos/pending/')
            return [{
                'filename': blob.name.replace('videos/pending/', ''),
                'url': self.generate_public_url(blob.name),
                'created': blob.time_created,
                'size': blob.size
            } for blob in blobs]
        except Exception as e:
            logger.error(f"Erreur lors de la liste des vidéos: {e}")
            raise

    def upload_file(self, file_content, filename, make_public=True):
        """Upload une vidéo en attente et la rendre publique si nécessaire"""
        try:
            blob = self.bucket.blob(f'videos/pending/{filename}')
            blob.cache_control = 'public, max-age=31536000'
            
            # Déterminer le content_type basé sur l'extension
            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'mp4'
            content_types = {
                'mp4': 'video/mp4',
                'webm': 'video/webm',
                'mov': 'video/quicktime',
                'avi': 'video/x-msvideo',
                'mkv': 'video/x-matroska'
            }
            blob.content_type = content_types.get(ext, 'video/mp4')
            
            blob.upload_from_file(file_content)

            if make_public:
                blob.make_public()

            logger.info(f"Vidéo uploadée avec succès: videos/pending/{filename}")
            url = self.generate_public_url(blob.name)
            logger.debug(f"URL générée: {url}")
            return url
        except Exception as e:
            logger.error(f"Erreur lors de l'upload: {e}")
            raise

    def promote_to_production(self, filename):
        """Promouvoir une vidéo en production et la rendre publique"""
        try:
            pending_path = f'videos/pending/{filename}'
            production_path = f'videos/production/{filename}'

            source = self.bucket.blob(pending_path)
            if not source.exists():
                raise Exception(f"Vidéo non trouvée: {pending_path}")

            # Copier vers production
            self.bucket.copy_blob(source, self.bucket, production_path)
            
            # Rendre publique
            destination = self.bucket.blob(production_path)
            destination.make_public()
            logger.info(f"Vidéo promue en production et rendue publique: {production_path}")
            
            # Supprimer l'original
            source.delete()
            
            return self.generate_public_url(production_path)
        except Exception as e:
            logger.error(f"Erreur lors de la promotion: {e}")
            raise
    
    def delete_pending_video(self, filename):
        """Supprimer une vidéo en attente"""
        try:
            blob_path = f'videos/pending/{filename}'
            blob = self.bucket.blob(blob_path)
            if not blob.exists():
                raise Exception(f"Vidéo non trouvée: {blob_path}")
                
            blob.delete()
            logger.info(f"Vidéo supprimée avec succès: {blob_path}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression: {e}")
            raise