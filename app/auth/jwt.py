from ..util import get_logger


class AzureADPublicKeysManager(object):
    def __init__(self):
        from datetime import datetime

        self.last_update = datetime.min
        self.certs = {}
        self.logger = get_logger(AzureADPublicKeysManager.__name__)
        self._jwks_uri = None

    def _refresh_certs(self) -> None:
        """Refresh the public certificates for every 12 hours."""
        from datetime import datetime, timedelta
        if datetime.utcnow() - self.last_update >= timedelta(hours=12):
            self.logger.info('Refresh the certificates')
            self._update_certs()
            self.last_update = datetime.utcnow()
        else:
            self.logger.info('Skip refreshing the certificates')

    def _update_certs(self) -> None:
        import requests
        from cryptography.x509 import load_pem_x509_certificate
        from cryptography.hazmat.backends import default_backend

        self.certs.clear()
        response = requests.get(self.jwks_uri)
        for key in response.json()['keys']:
            cert_str = "-----BEGIN CERTIFICATE-----\n{}\n-----END CERTIFICATE-----\n".format(key['x5c'][0])
            cert_obj = load_pem_x509_certificate(cert_str.encode('utf-8'), default_backend())
            public_key = cert_obj.public_key()
            self.logger.info('Create public key for {} from cert: \n{}'.format(key['kid'], cert_str))
            self.certs[key['kid']] = public_key

    @property
    def jwks_uri(self) -> str:
        """Delay load jwks uri from app to prevent circular dependencies."""
        if not self._jwks_uri:
            from ..main import app
            return app.config['auth_jwks_uri']

        return self._jwks_uri

    def get_public_key(self, key_id: str):
        self._refresh_certs()
        return self.certs[key_id]


class AzureJWS(object):
    def __init__(self, id_token: str):
        import base64
        import json
        self.id_token = id_token
        self.header = json.loads(base64.b64decode(self.id_token.split('.')[0]).decode('utf-8'))

        self._audience = None
        self._payload = None

    @property
    def audience(self) -> str:
        """Delay load jwks uri from app to prevent circular dependencies."""
        if not self._audience:
            from ..main import app
            return app.config['auth_client_id']

        return self._audience

    @property
    def key_id(self) -> str:
        return self.header['kid']

    @property
    def payload(self) -> dict:
        if not self._payload:
            import jwt
            public_key = _AZURE_AD_PUBLIC_KEYS_MANAGER.get_public_key(self.key_id)
            self._payload = jwt.decode(self.id_token, public_key, audience=self.audience)

        return self._payload


_AZURE_AD_PUBLIC_KEYS_MANAGER = AzureADPublicKeysManager()
