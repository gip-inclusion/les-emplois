import datetime


# This expiration time has been set to 24 hours because Inclusion Connect's
# email adress verification link is valid 24 hours.
OIDC_STATE_EXPIRATION = datetime.timedelta(hours=24)
