from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp
from flask_babel import lazy_gettext as _l

class RegistrationForm(FlaskForm):
    username = StringField(
        _l('Nom d\'utilisateur'), 
        validators=[
            DataRequired(message=_l("Le nom d'utilisateur est requis.")),
            Length(min=3, max=25, message=_l("Le nom d'utilisateur doit comporter entre 3 et 25 caractères."))
        ]
    )
    email = StringField(
        _l('Saisir mon addresse e-mail'), 
        validators=[
            DataRequired(message=_l("L'email est requis.")),
            Email(message=_l("Ceci n'est pas une adresse email valide."))
        ]
    )
    password = PasswordField(
        _l('Saisir mon mot de passe'), 
        validators=[
            DataRequired(message=_l("Le mot de passe est requis.")),
            Length(min=8, message=_l("Le mot de passe doit comporter au moins 8 caractères.")),
            Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 
                   message=_l("Le mot de passe doit contenir au moins une majuscule, une minuscule et un chiffre."))
        ]
    )
    confirm_password = PasswordField(
        _l('Confirmer le mot de passe'), 
        validators=[
            DataRequired(message=_l("Veuillez confirmer votre mot de passe.")),
            EqualTo('password', message=_l('Les mots de passe ne correspondent pas.'))
        ]
    )
    newsletter_subscription = BooleanField(_l('Abonnez-vous à notre lettre d\'informations.'))
    privacy_policy = BooleanField(
        _l('J\'accepte la politique de confidentialité de Tilto'),
        validators=[DataRequired(message=_l("Vous devez accepter la politique de confidentialité pour vous inscrire."))]
    )
    submit = SubmitField(_l('S\'inscrire'))

class LoginForm(FlaskForm):
    username = StringField(
        _l('Saisir mon addresse e-mail'), 
        validators=[
            DataRequired(message=_l("L'email est requis."))
        ]
    )
    password = PasswordField(
        _l('Saisir mon mot de passe'), 
        validators=[
            DataRequired(message=_l("Le mot de passe est requis."))
        ]
    )
    remember = BooleanField(_l('Se souvenir de moi')) 
    submit = SubmitField(_l('Se connecter'))

class ChangePasswordForm(FlaskForm):
    ancien_mot_de_passe = PasswordField(
        _l('Ancien mot de passe'), 
        validators=[
            DataRequired(message=_l("L'ancien mot de passe est requis."))
        ]
    )
    nouveau_mot_de_passe = PasswordField(
        _l('Nouveau mot de passe'), 
        validators=[
            DataRequired(message=_l("Le nouveau mot de passe est requis.")),
            Length(min=8, message=_l("Le nouveau mot de passe doit comporter au moins 8 caractères.")),
            Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 
                   message=_l("Le nouveau mot de passe doit contenir au moins une majuscule, une minuscule et un chiffre."))
        ]
    )
    confirmer_mot_de_passe = PasswordField(
        _l('Confirmer le nouveau mot de passe'), 
        validators=[
            DataRequired(message=_l("Veuillez confirmer le nouveau mot de passe.")),
            EqualTo('nouveau_mot_de_passe', message=_l('Les nouveaux mots de passe doivent correspondre.'))
        ]
    )
    submit = SubmitField(_l('Changer le mot de passe'))

class TwoFactorForm(FlaskForm):
    token = StringField(
        _l('Code 2FA'), 
        validators=[
            DataRequired(message=_l("Le code 2FA est requis.")),
            Length(min=6, max=6, message=_l("Le code 2FA doit comporter 6 chiffres."))
        ]
    )
    submit = SubmitField(_l('Valider'))


class RequestResetForm(FlaskForm):
    email = StringField(
        _l('Email'), 
        validators=[
            DataRequired(message=_l("L'email est requis.")),
            Email(message=_l("Ceci n'est pas une adresse email valide."))
        ]
    )
    submit = SubmitField(_l('Demander la réinitialisation'))

class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        _l('Nouveau mot de passe'), 
        validators=[
            DataRequired(message=_l("Le mot de passe est requis.")),
            Length(min=8, message=_l("Le mot de passe doit comporter au moins 8 caractères.")),
            Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 
                   message=_l("Le mot de passe doit contenir au moins une majuscule, une minuscule et un chiffre."))
        ]
    )
    confirm_password = PasswordField(
        _l('Confirmer le mot de passe'), 
        validators=[
            DataRequired(message=_l("Veuillez confirmer votre mot de passe.")),
            EqualTo('password', message=_l('Les mots de passe ne correspondent pas.'))
        ]
    )
    submit = SubmitField(_l('Réinitialiser le mot de passe'))