from datetime import datetime, timedelta
import base64
import json

import jwt
import requests
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.backends import default_backend

from morocco.util import get_logger


class AzureADPublicKeysManager(object):
    def __init__(self, jwks_uri: str, client_id: str):
        self._logger = get_logger(AzureADPublicKeysManager.__name__)
        self._last_update = datetime.min
        self._certs = {}
        self._jwks_uri = jwks_uri
        self._client_id = client_id

    def _refresh_certs(self) -> None:
        """Refresh the public certificates for every 12 hours."""
        if datetime.utcnow() - self._last_update >= timedelta(hours=12):
            self._logger.info('Refresh the certificates')
            self._update_certs()
            self._last_update = datetime.utcnow()
        else:
            self._logger.info('Skip refreshing the certificates')

    def _update_certs(self) -> None:
        self._certs.clear()
        response = requests.get(self._jwks_uri)
        for key in response.json()['keys']:
            cert_str = "-----BEGIN CERTIFICATE-----\n{}\n-----END CERTIFICATE-----\n".format(key['x5c'][0])
            cert_obj = load_pem_x509_certificate(cert_str.encode('utf-8'), default_backend())
            public_key = cert_obj.public_key()
            self._logger.info('Create public key for {} from cert: \n{}'.format(key['kid'], cert_str))
            self._certs[key['kid']] = public_key

    def get_public_key(self, key_id: str):
        self._refresh_certs()
        return self._certs[key_id]

    def get_id_token_payload(self, id_token: str):

        header = json.loads(base64.b64decode(id_token.split('.')[0]).decode('utf-8'))
        key_id = header['kid']
        public_key = self.get_public_key(key_id)

        return jwt.decode(id_token, public_key, audience=self._client_id)
