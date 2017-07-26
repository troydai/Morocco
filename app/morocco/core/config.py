import os
from flask import Config

from morocco.util import get_logger
from morocco.auth import AzureADPublicKeysManager


def load_config(app, project_setting_type) -> None:
    logger = get_logger(__name__)

    app.config['is_local_server'] = os.environ.get('MOROCCO_LOCAL_SERVER') == 'True'

    for setting in project_setting_type.query.all():
        logger.info('add setting {}'.format(setting.name))
        app.config[setting.name] = setting.value

    init_auth_config(app.config)


def init_auth_config(config: Config) -> None:
    import requests

    config_url = 'https://login.microsoftonline.com/{}/.well-known/openid-configuration' \
        .format(config['MOROCCO_AUTH_TENANT'])
    response = requests.get(config_url)
    if response.status_code != 200:
        raise EnvironmentError('Fail to request Azure AD OpenID configuration from {}.'.format(config_url))

    result = response.json()
    config['auth_authorization_endpoint'] = result['authorization_endpoint']
    config['auth_token_endpoint'] = result['token_endpoint']
    config['auth_jwks_uri'] = result['jwks_uri']
    config['auth_signout_uri'] = result['end_session_endpoint']
    config['auth_public_key_manager'] = AzureADPublicKeysManager(config['auth_jwks_uri'],
                                                                 config['MOROCCO_AUTH_CLIENT_ID'])
