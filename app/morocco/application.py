import logging
import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

app = Flask(__name__)

if 'MOROCCO_DATABASE_URI' not in os.environ:
    raise EnvironmentError('Missing environment MOROCCO_DATABASE_URI')

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['MOROCCO_DATABASE_URI']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


def load_config_from_db():
    import requests
    from .models import DbProjectSetting
    from .auth import AzureADPublicKeysManager

    if not app.debug:
        app.config['PREFERRED_URL_SCHEME'] = 'https'

    if app.debug:
        logging.basicConfig(level=logging.DEBUG)

    for setting in DbProjectSetting.query.all():
        app.config[setting.name] = setting.value

    if not app.secret_key:
        app.secret_key = os.environ.get('MOROCCO_SECRET_KEY', 'session secret key for local testing')

    app.config['is_local_server'] = os.environ.get('MOROCCO_LOCAL_SERVER') == 'True'

    config_url = 'https://login.microsoftonline.com/{}/.well-known/openid-configuration' \
        .format(app.config['MOROCCO_AUTH_TENANT'])
    response = requests.get(config_url)
    if response.status_code != 200:
        raise EnvironmentError('Fail to request Azure AD OpenID configuration from {}.'.format(config_url))

    result = response.json()
    app.config['auth_authorization_endpoint'] = result['authorization_endpoint']
    app.config['auth_token_endpoint'] = result['token_endpoint']
    app.config['auth_jwks_uri'] = result['jwks_uri']
    app.config['auth_signout_uri'] = result['end_session_endpoint']
    app.config['auth_public_key_manager'] = AzureADPublicKeysManager(app.config['auth_jwks_uri'],
                                                                     app.config['MOROCCO_AUTH_CLIENT_ID'])
