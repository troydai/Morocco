"""
The utilities facilitate the authentication through Azure AD Open ID

Reference:
  - https://docs.microsoft.com/en-us/azure/active-directory/develop/active-directory-protocols-openid-connect-code
"""

# pylint: disable=unused-import

from morocco.auth.jwt import AzureADPublicKeysManager
from morocco.auth.openid_actions import openid_logout, openid_callback, openid_login
