import time

import jwt
from django.conf import settings


# Metabase private / signed URLs
# See:
# * https://www.metabase.com/docs/latest/enterprise-guide/full-app-embedding.html
# * https://github.com/jpadilla/pyjwt
# * https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py
def _get_token(payload):
    return jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")


def metabase_embedded_url(dashboard_id):
    """
    Creates an embed/signed URL for embedded Metabase dashboards:
    * expiration delay of token set at 24H
    * do not display title of the dashboard in the iframe
    """
    payload = {"resource": {"dashboard": dashboard_id}, "params": {}, "exp": round(time.time()) + (60 * 60 * 24)}
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload) + "#titled=false"
