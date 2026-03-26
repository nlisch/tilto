from flask_login import UserMixin
from flask_login import AnonymousUserMixin
from flask import g, session, current_app
import pyotp
from itsdangerous import URLSafeTimedSerializer
import os
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class User(UserMixin):
    def __init__(self, user_id, username, email, user_status, country_code='FR', two_factor_secret=None, nb_accompagnement=None, firstname=None, lastname=None):
        self.id = user_id
        self.username = username
        self.email = email
        self.user_status = user_status or 'customer'  # Valeur par défaut
        self.country_code = country_code
        self.two_factor_secret = two_factor_secret
        self.password_hash = None
        self.current_quiz_session = None
        self.nb_accompagnement = nb_accompagnement  # Champ pour les coachs
        self.firstname = firstname  # Prénom
        self.lastname = lastname    # Nom de famille

    # Propriétés requises par Flask-Login
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False
    
    @property
    def is_lead(self):
        """Vérifie si l'utilisateur est un lead."""
        return self.user_status == 'lead'
    
    @property 
    def is_customer(self):
        """Vérifie si l'utilisateur est un client."""
        return self.user_status == 'customer'
    
    @property
    def is_coach(self):
        """Vérifie si l'utilisateur est un coach."""
        return self.user_status == 'coach'

    @property 
    def is_admin_user(self):
        """Vérifie si l'utilisateur a des privilèges administrateur."""
        return self.user_status == 'admin'

    def get_id(self):
        return str(self.id)
    
    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        password_hash = generate_password_hash(password)
        self.password_hash = password_hash
        return password_hash  # Retourne le hash pour pouvoir l'utiliser lors de l'insertion en BD
    
    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:  # Vérification que le hash existe
            return False
        return check_password_hash(self.password_hash, password)
    
    def get_two_factor_uri(self):
        if not self.two_factor_secret:  # Vérification que le secret existe
            return None
        return pyotp.totp.TOTP(self.two_factor_secret).provisioning_uri(
            name=self.email,
            issuer_name="Tilto"
        )

    @staticmethod
    def generate_user_access_token(cursor, user_id):
        """
        Génère un token d'accès unique pour un utilisateur
        
        Args:
            cursor: Curseur MySQL
            user_id (int): ID de l'utilisateur
            
        Returns:
            str: Token d'accès généré
        """
        try:
            # Générer un nouveau token
            token = f"{uuid.uuid4()}-{int(datetime.now().timestamp())}"
            
            # Mettre à jour dans la base de données
            cursor.execute("""
                UPDATE users
                SET access_token = %s
                WHERE user_id = %s
            """, (token, user_id))
            
            return token
        except Exception as e:
            logger.error(f"Erreur lors de la génération du token d'accès pour l'utilisateur {user_id}: {e}")
            return None
  
    def verify_two_factor_token(self, token):
        if not self.two_factor_secret:
            return False
        
        # Nettoyage du token (supprimer espaces et caractères non numériques)
        import re
        token = re.sub(r'[^0-9]', '', token)
        
        totp = pyotp.TOTP(self.two_factor_secret)
        # Ajouter une fenêtre de validité de ±1 intervalle (30 secondes avant/après)
        return totp.verify(token, valid_window=1)

    def start_quiz_session(self, quiz_id):
        """Crée une nouvelle session de quiz pour l'utilisateur"""
        self.current_quiz_session = str(uuid.uuid4())
        return self.current_quiz_session

    def validate_quiz_session(self, session_id):
        """Vérifie si la session de quiz est valide pour l'utilisateur"""
        return self.current_quiz_session == session_id

    def get_reset_token(self, expires_sec=1800):
        """Génère un token sécurisé pour la réinitialisation du mot de passe"""
        s = URLSafeTimedSerializer(os.environ.get('SECRET_KEY'))
        # Inclure le type d'utilisateur dans les données sérialisées
        return s.dumps({'user_id': self.id, 'user_status': self.user_status}, salt='password-reset-salt')

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        """Vérifie un token de réinitialisation de mot de passe"""
        s = URLSafeTimedSerializer(os.environ.get('SECRET_KEY'))
        try:
            data = s.loads(token, salt='password-reset-salt', max_age=expires_sec)
            # Si besoin, vous pouvez utiliser le user_status
            return data['user_id']
        except:
            return None

    def generate_email_verification_token(self):
        """Génère un token de vérification d'email"""
        s = URLSafeTimedSerializer(os.environ.get('SECRET_KEY'))
        return s.dumps({'user_id': self.id, 'email': self.email}, salt='email-verification-salt')

    def verify_email_verification_token(token, expires_sec=86400):  # 24 heures
        """Vérifie un token de vérification d'email"""
        s = URLSafeTimedSerializer(os.environ.get('SECRET_KEY'))
        try:
            data = s.loads(token, salt='email-verification-salt', max_age=expires_sec)
            return data['user_id']
        except:
            return None

    def get_by_id(user_id, cursor=None):
        """
        Récupère un utilisateur par son ID.
        """
        if cursor is None:
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            should_close = True
        else:
            should_close = False
        
        try:
            cursor.execute("""
                SELECT user_id, username, email, user_status, country_code, two_factor_secret, nb_accompagnement, firstname, lastname
                FROM users 
                WHERE user_id = %s
            """, (user_id,))
            user_data = cursor.fetchone()
            
            if user_data:
                user = User(
                    user_id=user_data[0],
                    username=user_data[1],
                    email=user_data[2],
                    user_status=user_data[3],
                    country_code=user_data[4],
                    two_factor_secret=user_data[5],
                    nb_accompagnement=user_data[6],
                    firstname=user_data[7],
                    lastname=user_data[8]
                )
                return user
            return None
        finally:
            if should_close:
                cursor.close()
            
    @staticmethod
    def get_by_email(email, cursor=None):
        """
        Récupère un utilisateur par son email.
        """
        if cursor is None:
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            should_close = True
        else:
            should_close = False
        
        try:
            cursor.execute("""
                SELECT user_id, username, email, user_status, country_code, two_factor_secret, nb_accompagnement, firstname, lastname
                FROM users 
                WHERE email = %s
            """, (email,))
            user_data = cursor.fetchone()
            
            if user_data:
                user = User(
                    user_id=user_data[0],
                    username=user_data[1],
                    email=user_data[2],
                    user_status=user_data[3],
                    country_code=user_data[4],
                    two_factor_secret=user_data[5],
                    nb_accompagnement=user_data[6],
                    firstname=user_data[7],
                    lastname=user_data[8]
                )
                return user
            return None
        finally:
            if should_close:
                cursor.close()

    @staticmethod
    def get_all_coaches(cursor=None):
        """
        Récupère tous les coachs (utilisateurs avec user_status = 'coach').
        """
        if cursor is None:
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            should_close = True
        else:
            should_close = False
        
        try:
            cursor.execute("""
                SELECT user_id, username, email, firstname, lastname, nb_accompagnement, created_at
                FROM users 
                WHERE user_status = 'coach'
                ORDER BY created_at DESC
            """)
            coaches = cursor.fetchall()
            return coaches
        finally:
            if should_close:
                cursor.close()

    @staticmethod
    def get_all_by_status(status, cursor=None):
        """
        Récupère tous les utilisateurs d'un statut donné.
        
        Args:
            status (str): Le statut à rechercher ('lead', 'customer', 'admin', 'coach')
            cursor: Curseur MySQL optionnel
            
        Returns:
            list: Liste des utilisateurs trouvés
        """
        if cursor is None:
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            should_close = True
        else:
            should_close = False
        
        try:
            cursor.execute("""
                SELECT user_id, username, email, firstname, lastname, user_status, nb_accompagnement, created_at
                FROM users 
                WHERE user_status = %s
                ORDER BY created_at DESC
            """, (status,))
            users = cursor.fetchall()
            return users
        finally:
            if should_close:
                cursor.close()

    def get_full_name(self):
        """Retourne le nom complet de l'utilisateur"""
        if self.firstname and self.lastname:
            return f"{self.firstname} {self.lastname}"
        elif self.firstname:
            return self.firstname
        elif self.lastname:
            return self.lastname
        else:
            return self.username

    def get_display_name(self):
        """Retourne le nom d'affichage préféré"""
        if self.firstname:
            return self.firstname
        else:
            return self.username

    def update_last_login(self, cursor=None):
        """Met à jour la date de dernière connexion"""
        if cursor is None:
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            should_close = True
        else:
            should_close = False
        
        try:
            cursor.execute("""
                UPDATE users 
                SET last_login = %s 
                WHERE user_id = %s
            """, (datetime.now(), self.id))
        finally:
            if should_close:
                cursor.close()

    def to_dict(self):
        """Convertit l'utilisateur en dictionnaire pour la sérialisation"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'user_status': self.user_status,
            'country_code': self.country_code,
            'firstname': self.firstname,
            'lastname': self.lastname,
            'full_name': self.get_full_name(),
            'display_name': self.get_display_name(),
            'nb_accompagnement': self.nb_accompagnement,
            'is_lead': self.is_lead,
            'is_customer': self.is_customer,
            'is_coach': self.is_coach,
            'is_admin': self.is_admin_user
        }

class CustomAnonymousUser(AnonymousUserMixin):
    @property
    def country_code(self):
        # Récupérer la langue de l'utilisateur
        lang_code = g.lang_code if hasattr(g, 'lang_code') else session.get('lang_code', 'fr')
        
        # Map des langues aux pays
        lang_to_country = {
            'fr': 'FR',
            'en': 'GB',
            # Ajoutez d'autres mappages si nécessaire
        }
        
        # Retourner le code pays correspondant ou FR par défaut
        return lang_to_country.get(lang_code, 'FR')
    
    @property
    def user_status(self):
        return None
    
    @property
    def is_lead(self):
        return False
    
    @property
    def is_customer(self):
        return False
    
    @property
    def is_coach(self):
        return False
    
    @property
    def is_admin_user(self):
        return False

    