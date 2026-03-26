# services/image_service.py
from google.cloud import storage
from PIL import Image
import io
import uuid
import logging
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app

logger = logging.getLogger(__name__)

class ImageService:
    def __init__(self):
        try:
            self.storage_client = storage.Client()
            self.bucket = self.storage_client.bucket(current_app.config['STORAGE_BUCKET'])
            self.cdn_url = current_app.config['CDN_URL']
            self.env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
            self.image_config = current_app.config['IMAGES']
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de ImageService: {e}")
            raise


    def generate_public_url(self, blob_path):
        #"""Génère une URL publique stable"""
        #return f"https://storage.googleapis.com/{self.bucket.name}/{blob_path}"
        """Génère une URL publique stable via le CDN"""
        return f"{self.cdn_url}/{blob_path}"

        
    def optimize_image(self, image_file):
        """Optimise l'image en WebP"""
        try:
            img = Image.open(image_file)
            
            if img.mode in ('RGBA', 'LA'):
                img = img.convert('RGBA')
            else:
                img = img.convert('RGB')
            
            if (img.size[0] > self.image_config['MAX_SIZE'][0] or 
                img.size[1] > self.image_config['MAX_SIZE'][1]):
                img.thumbnail(self.image_config['MAX_SIZE'], Image.LANCZOS)
            
            webp_io = io.BytesIO()
            img.save(webp_io, 'WEBP', 
                    quality=self.image_config['QUALITY'], 
                    method=6)
            webp_io.seek(0)
            
            return webp_io
        except Exception as e:
            logger.error(f"Erreur lors de l'optimisation de l'image: {e}")
            raise

    def generate_filename(self, original_filename):
        """Génère un nom de fichier unique avec date"""
        try:
            date_prefix = datetime.now().strftime('%Y/%m')
            filename = secure_filename(original_filename)
            unique_id = str(uuid.uuid4())[:8]
            return f"{date_prefix}/{unique_id}_{filename.rsplit('.', 1)[0]}.webp"
        except Exception as e:
            logger.error(f"Erreur lors de la génération du nom de fichier: {e}")
            raise

    def list_pending_images(self):
        """Liste les images en attente de validation"""
        try:
            blobs = self.bucket.list_blobs(prefix='pending/')
            return [{
                'filename': blob.name.replace('pending/', ''),
                'url': self.generate_public_url(blob.name),  # Assurez-vous que blob.name est correct
                'created': blob.time_created,
                'size': blob.size
            } for blob in blobs]
        except Exception as e:
            logger.error(f"Erreur lors de la liste des images: {e}")
            raise

    def upload_file(self, file_content, filename, make_public=True):
        """Upload une image en attente et la rendre publique si nécessaire"""
        try:

            blob = self.bucket.blob(f'pending/{filename}')
            blob.cache_control = 'public, max-age=31536000, immutable'
            blob.content_type = 'image/webp'
            blob.upload_from_file(file_content)

            if make_public:
                blob.make_public()

            logger.info(f"Image uploadée avec succès: pending/{filename}")
            url = self.generate_public_url(blob.name)
            logger.debug(f"URL générée: {url}")
            return url
        except Exception as e:
            logger.error(f"Erreur lors de l'upload: {e}")
            raise

    def promote_to_production(self, filename):
        """Promouvoir une image en production et la rendre publique"""
        try:

            # Récupérer le chemin complet depuis pending
            pending_path = f'pending/{filename}'
            production_path = f'production/{filename}'

            source = self.bucket.blob(pending_path)
            if not source.exists():
                raise Exception(f"Image non trouvée: {pending_path}")

            destination = self.bucket.blob(production_path)
            
            # Utiliser copy_blob pour copier l'objet
            self.bucket.copy_blob(source, self.bucket, production_path)
            
            # Rendre l'objet en production public
            destination.cache_control = 'public, max-age=31536000, immutable'
            destination.patch()
            destination.make_public()
            logger.info(f"Image promue en production et rendue publique: {production_path}")
            
            # Supprimer l'objet original dans pending
            source.delete()
            
            # Retourner l'URL publique de l'objet en production
            return self.generate_public_url(production_path)
        except Exception as e:
            logger.error(f"Erreur lors de la promotion: {e}")
            raise
    
    def delete_pending_image(self, filename):
        """Supprimer une image en attente"""
        try:
            blob_path = f'pending/{filename}'
            blob = self.bucket.blob(blob_path)
            if not blob.exists():
                raise Exception(f"Image non trouvée: {blob_path}")
                
            blob.delete()
            logger.info(f"Image supprimée avec succès: {blob_path}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression: {e}")
            raise
