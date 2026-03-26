# blueprints/videos.py
from flask import Blueprint, request, jsonify, current_app, render_template
from services.video_service import VideoService
import logging
from decorators import admin_required

logger = logging.getLogger(__name__)

video_bp = Blueprint('videos', __name__, url_prefix='/api/videos')

@video_bp.route('/upload', methods=['POST'])
@admin_required
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'Aucune vidéo fournie'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'Aucun fichier sélectionné'}), 400
    
    # Vérification de l'extension
    allowed_extensions = current_app.config['VIDEOS']['ALLOWED_EXTENSIONS']
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'error': 'Type de fichier non autorisé'}), 400
    
    try:
        video_service = VideoService()
        
        # Validation de la taille
        video_service.validate_video(file)
        
        # Génération nom fichier
        filename = video_service.generate_filename(file.filename)
        
        # Upload (pas d'optimisation, upload direct)
        url = video_service.upload_file(file, filename)
        
        return jsonify({
            'url': url,
            'filename': filename,
            'success': True
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'upload de la vidéo: {e}")
        return jsonify({'error': str(e)}), 500

@video_bp.route('/promote/<path:filename>', methods=['POST'])
@admin_required
def promote_video(filename):
    try:
        video_service = VideoService()
        url = video_service.promote_to_production(filename)
        return jsonify({
            'success': True,
            'url': url
        })
    except Exception as e:
        logger.error(f"Erreur lors de la promotion: {e}")
        return jsonify({'error': str(e)}), 500

@video_bp.route('/pending', methods=['GET'])
@admin_required
def list_pending_videos():
    try:
        video_service = VideoService()
        videos = video_service.list_pending_videos()
        return jsonify(videos)
    except Exception as e:
        logger.error(f"Erreur lors de la liste des vidéos: {e}")
        return jsonify({'error': str(e)}), 500

@video_bp.route('/delete/<path:filename>', methods=['DELETE'])
@admin_required
def delete_video(filename):
    try:
        video_service = VideoService()
        video_service.delete_pending_video(filename)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Erreur lors de la suppression: {e}")
        return jsonify({'error': str(e)}), 500

@video_bp.route('/video_handler')
@admin_required
def video_handler():
    return render_template('admin/video_handler.html')