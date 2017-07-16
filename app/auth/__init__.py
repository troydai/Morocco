"""
The utilities facilitate the authentication through Azure AD Open ID

Reference:
  - https://docs.microsoft.com/en-us/azure/active-directory/develop/active-directory-protocols-openid-connect-code
"""

from .jwt import AzureJWS
from .config import init_auth_config
from .openid_actions import openid_signout, openid_callback, openid_login
