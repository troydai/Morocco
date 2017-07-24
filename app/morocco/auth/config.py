from flask import Config
from flask_login import UserMixin
from morocco.auth.jwt import AzureADPublicKeysManager


class User(UserMixin):
    def __init__(self, user_id: str):
        self.id = user_id  # pylint: disable=invalid-name


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
