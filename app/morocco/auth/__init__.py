"""
The utilities facilitate the authentication through Azure AD Open ID

Reference:
  - https://docs.microsoft.com/en-us/azure/active-directory/develop/active-directory-protocols-openid-connect-code
"""

from morocco.auth.jwt import AzureJWS
from morocco.auth.config import init_auth_config
from morocco.auth.openid_actions import openid_signout, openid_callback, openid_login
