import datetime


# This expiration time has been set to 1 month.
# This will allow to help users that don't receive the email.
# IC support team will manually validate the email in IC and ask the user to log in IC.
# IC will then automatically redirect the user to our callback view, and it may be more than
# 1 day after the state was generated, so keeping it "open" for a month is simpler.
OIDC_STATE_EXPIRATION = datetime.timedelta(days=30)
OIDC_STATE_CLEANUP = datetime.timedelta(days=30 * 2)
