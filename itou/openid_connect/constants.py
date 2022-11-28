import datetime


# This expiration time has been chosen arbitrarily.
OIDC_STATE_EXPIRATION = datetime.timedelta(hours=1)
OIDC_STATE_CLEANUP = datetime.timedelta(days=30)
