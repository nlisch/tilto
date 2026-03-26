from flask_mysqldb import MySQL
from flask_login import LoginManager
from models.user_model import CustomAnonymousUser 
from flask_wtf.csrf import CSRFProtect
from flask_oauthlib.client import OAuth
from flask_babel import Babel
from flask_talisman import Talisman
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

# Initialisation des extensions sans les lier à l'app
mysql = MySQL()
login_manager = LoginManager()
login_manager.anonymous_user = CustomAnonymousUser
csrf = CSRFProtect()
oauth = OAuth()
babel = Babel()
talisman = Talisman()
cors = CORS()
mail = Mail()
limiter = Limiter(key_func=get_remote_address, default_limits=[], headers_enabled=True)
