import time

import jwt
from django.conf import settings


SIAE_FILTER_KEY = "identifiant_de_la_structure"
DEPARTMENT_FILTER_KEY = "d%C3%A9partement"
REGION_FILTER_KEY = "r%C3%A9gion"


# Metabase private / signed URLs
# See:
# * https://www.metabase.com/docs/latest/enterprise-guide/full-app-embedding.html
# * https://github.com/jpadilla/pyjwt
# * https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py
def _get_token(payload):
    return jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")


def metabase_embedded_url(dashboard_id, params={}, with_title=False):
    """
    Creates an embed/signed URL for embedded Metabase dashboards:
    * expiration delay of token set at 10 minutes, kept short on purpose due to the fact that during this short time
      the user can share the iframe URL to non authorized third parties
    * do not display title of the dashboard in the iframe
    * optional parameters typically for locked filters (e.g. allow viewing data of one departement only)
    """
    payload = {"resource": {"dashboard": dashboard_id}, "params": params, "exp": round(time.time()) + (10 * 60)}
    is_titled = "true" if with_title else "false"
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload) + f"#titled={is_titled}"
