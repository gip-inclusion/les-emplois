from django.conf import settings


# https://github.com/numerique-gouv/agentconnect-documentation/blob/main/doc_fs/donnees_fournies.md
# We should not need to add the email, given_name and usual_name but it doesn"t work without them...
PRO_CONNECT_SCOPES = "openid email given_name usual_name custom"

PRO_CONNECT_CLIENT_ID = settings.PRO_CONNECT_CLIENT_ID
PRO_CONNECT_CLIENT_SECRET = settings.PRO_CONNECT_CLIENT_SECRET

PRO_CONNECT_ENDPOINT_AUTHORIZE = f"{settings.PRO_CONNECT_BASE_URL}/authorize"
PRO_CONNECT_ENDPOINT_TOKEN = f"{settings.PRO_CONNECT_BASE_URL}/token"
PRO_CONNECT_ENDPOINT_USERINFO = f"{settings.PRO_CONNECT_BASE_URL}/userinfo"
PRO_CONNECT_ENDPOINT_LOGOUT = f"{settings.PRO_CONNECT_BASE_URL}/session/end"

# This timeout (in seconds) has been chosen arbitrarily.
PRO_CONNECT_TIMEOUT = 60

PRO_CONNECT_SESSION_KEY = "pro_connect"

PRO_CONNECT_FT_IDP_HINT = settings.PRO_CONNECT_FT_IDP_HINT
