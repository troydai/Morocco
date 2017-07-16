import os
from flask import Config


def init_auth_config(config: Config) -> None:
    import requests

    try:
        config['auth_tenant'] = os.environ['MOROCCO_AUTH_TENANT']
        config['auth_client_id'] = os.environ['MOROCCO_AUTH_CLIENT_ID']
        config['auth_secret'] = os.environ['MOROCCO_AUTH_SECRET']
    except KeyError as ex:
        raise EnvironmentError('Missing environment variable for configuration. [{}]'.format(ex))


    config_url = 'https://login.microsoftonline.com/{}/.well-known/openid-configuration' \
        .format(config['auth_tenant'])
    response = requests.get(config_url)
    if response.status_code != 200:
        raise EnvironmentError('Fail to request Azure AD OpenID configuration from {}.'.format(config_url))

    result = response.json()
    config['auth_authorization_endpoint'] = result['authorization_endpoint']
    config['auth_token_endpoint'] = result['token_endpoint']
    config['auth_jwks_uri'] = result['jwks_uri']
    config['auth_signout_uri'] = result['end_session_endpoint']
