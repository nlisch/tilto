from .auth import auth_bp
from .quiz import quiz_bp
from .quiz_analysis import quiz_analysis_bp
from .user import user_bp
from .images import image_bp
from .videos import video_bp
from .tokens import token_bp
from .coupons import coupons_bp
from .cookie import cookie_bp
from .audio import audio_bp
from .lead import lead_bp
from .dashboard import dashboard_bp
from .audio_capsule import audio_capsule_bp
from .admin import admin_bp
from .chat import chat_bp
from .async_analysis import async_analysis_bp
from .help_requests import help_requests_bp


# Si vous voulez contrôler ce qui est disponible lors de l'utilisation de "from routes import *"
__all__ = ['auth_bp', 'quiz_bp', 'quiz_analysis_bp', 'user_bp', 'image_bp', 'video_bp', 'token_bp', 'coupons_bp', 'cookie_bp', 'audio_bp', 'lead_bp', 'audio_capsule_bp', 'admin_bp', 'chat_bp', 'async_analysis_bp', 'help_requests_bp']

# Vous pouvez également ajouter des variables ou des configurations spécifiques aux routes ici si nécessaire