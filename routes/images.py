# blueprints/images.py
from flask import Blueprint, request, jsonify, current_app, render_template
import os
from services import ImageService
import logging
from decorators import admin_required

logger = logging.getLogger(__name__)
image_bp = Blueprint('images', __name__, url_prefix='/api/images')


@image_bp.route('/upload', methods=['POST'])
@admin_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': 'Aucune image fournie'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
    
    # Vérification de l'extension
    allowed_extensions = current_app.config['IMAGES']['ALLOWED_EXTENSIONS']
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'error': 'Type de fichier non autorisé'}), 400
    
    try:
        image_service = ImageService()
        
        # Optimisation
        optimized_image = image_service.optimize_image(file)
        
        # Génération nom fichier
        filename = image_service.generate_filename(file.filename)
        
        # Upload
        url = image_service.upload_file(optimized_image, filename)
        
        return jsonify({
            'url': url,
            'filename': filename,
            'success': True
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'upload de l'image: {e}")
        return jsonify({'error': str(e)}), 500

@image_bp.route('/promote/<path:filename>', methods=['POST'])
@admin_required
def promote_image(filename):
    try:
        image_service = ImageService()
        url = image_service.promote_to_production(filename)
        return jsonify({
            'success': True,
            'url': url
        })
    except Exception as e:
        logger.error(f"Erreur lors de la promotion: {e}")
        return jsonify({'error': str(e)}), 500

@image_bp.route('/pending', methods=['GET'])
@admin_required
def list_pending_images():
    try:
        image_service = ImageService()
        images = image_service.list_pending_images()
        return jsonify(images)
    except Exception as e:
        logger.error(f"Erreur lors de la liste des images: {e}")
        return jsonify({'error': str(e)}), 500

@image_bp.route('/delete/<path:filename>', methods=['DELETE'])
@admin_required
def delete_image(filename):
    try:
        image_service = ImageService()
        image_service.delete_pending_image(filename)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Erreur lors de la suppression: {e}")
        return jsonify({'error': str(e)}), 500

@image_bp.route('/invalidate-cache', methods=['POST'])
@admin_required
def invalidate_cache():
    data = request.get_json()
    paths = data.get('paths', [])

    if not paths:
        return jsonify({'error': 'Aucun chemin spécifié'}), 400

    try:
        cache_service = CacheService()
        response = cache_service.invalidate_cache('tilto-images-urlmap', paths)
        return jsonify({'success': True, 'response': response}), 200
    except Exception as e:
        logger.error(f"Erreur lors de l'invalidation du cache: {e}")
        return jsonify({'error': str(e)}), 500

@image_bp.route('/image_handler')
@admin_required
def image_handler():
    return render_template('admin/image_handler.html')