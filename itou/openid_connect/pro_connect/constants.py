from django.conf import settings


# https://github.com/france-connect/Documentation-AgentConnect/blob/main/doc_fs/technique_fca/technique_fca_scope.md
PRO_CONNECT_SCOPES = "openid email given_name usual_name"

PRO_CONNECT_CLIENT_ID = settings.PRO_CONNECT_CLIENT_ID
PRO_CONNECT_CLIENT_SECRET = settings.PRO_CONNECT_CLIENT_SECRET

PRO_CONNECT_ENDPOINT_BASE = f"{settings.PRO_CONNECT_BASE_URL}/api/v2"
PRO_CONNECT_ENDPOINT_AUTHORIZE = f"{PRO_CONNECT_ENDPOINT_BASE}/authorize"
PRO_CONNECT_ENDPOINT_TOKEN = f"{PRO_CONNECT_ENDPOINT_BASE}/token"
PRO_CONNECT_ENDPOINT_USERINFO = f"{PRO_CONNECT_ENDPOINT_BASE}/userinfo"
PRO_CONNECT_ENDPOINT_LOGOUT = f"{PRO_CONNECT_ENDPOINT_BASE}/session/end"

# These expiration times have been chosen arbitrarily.
PRO_CONNECT_TIMEOUT = 60

PRO_CONNECT_SESSION_KEY = "pro_connect"
