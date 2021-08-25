import time

import jwt
from django.conf import settings

from itou.common_apps.address.departments import DEPARTMENTS


# Metabase private / signed URLs
# See:
# * https://www.metabase.com/docs/latest/enterprise-guide/full-app-embedding.html
# * https://github.com/jpadilla/pyjwt
# * https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py
def _get_token(payload):
    return jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")


def metabase_embedded_url(dashboard_id, department=None):
    """
    Creates an embed/signed URL for embedded Metabase dashboards:
    * expiration delay of token set at 10 minutes, kept short on purpose due to the fact that during this short time
      the user can share the iframe URL to non authorized third parties
    * do not display title of the dashboard in the iframe
    * optional parameters for when you want to lock a filter (e.g. allow viewing data of one departement only)
    """
    params = {}
    if department is not None:
        # `é` in `département` is converted to `_` on metabase side.
        params["d_partement"] = DEPARTMENTS[department]

    payload = {"resource": {"dashboard": dashboard_id}, "params": params, "exp": round(time.time()) + (10 * 60)}
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload) + "#titled=false"
