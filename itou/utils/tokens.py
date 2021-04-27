from datetime import datetime

from django.conf import settings
from django.core.signing import Signer
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.http import base36_to_int, int_to_base36


SIAE_SIGNUP_MAGIC_LINK_TIMEOUT = 2 * 7 * 24 * 3600


class SiaeSignupTokenGenerator:
    """
    Strategy object used to generate and check tokens for the secure
    siae signup mechanism.
    Heavily inspired from django PasswordResetTokenGenerator :
    https://github.com/django/django/blob/master/django/contrib/auth/tokens.py
    """

    key_salt = "itou.utils.tokens.SiaeSignupTokenGenerator"
    secret = settings.SECRET_KEY

    def make_token(self, siae):
        """
        Return a token that can be used once to do a signup
        for the given siae and is valid only for a limited time.
        """
        return self._make_token_with_timestamp(siae, self._num_seconds(self._now()))

    def check_token(self, siae, token):
        """
        Check that a siae signup token is correct for a given siae.
        """
        if not (siae and token):
            return False
        # Parse the token
        try:
            timestamp_b36, _ = token.split("-")
        except ValueError:
            return False

        try:
            timestamp = base36_to_int(timestamp_b36)
        except ValueError:
            return False

        # Check that the timestamp/uid has not been tampered with
        if not constant_time_compare(self._make_token_with_timestamp(siae, timestamp), token):
            return False

        # Check the timestamp is within limit.
        if (self._num_seconds(self._now()) - timestamp) > SIAE_SIGNUP_MAGIC_LINK_TIMEOUT:
            return False

        return True

    def _make_token_with_timestamp(self, siae, timestamp):
        # timestamp is number of seconds since 2001-1-1. Converted to base 36,
        # this gives us a 6 digit string until about 2069.
        timestamp_b36 = int_to_base36(timestamp)
        hash_string = salted_hmac(
            self.key_salt, self._make_hash_value(siae, timestamp), secret=self.secret
        ).hexdigest()[
            ::2
        ]  # Limit to 20 characters to shorten the URL.
        return "%s-%s" % (timestamp_b36, hash_string)

    def _make_hash_value(self, siae, timestamp):
        """
        Hash the siae's primary key and some siae state (its number of members)
        that's sure to change after a signup to produce a token that is invalidated
        as soon as it is used.
        Moreover SIAE_SIGNUP_MAGIC_LINK_TIMEOUT eventually
        invalidates the token anyway.
        """
        return str(siae.pk) + str(siae.members.count()) + str(timestamp)

    def _num_seconds(self, dt):
        return int((dt - datetime(2001, 1, 1)).total_seconds())

    def _now(self):
        # Used for mocking in tests
        return datetime.now()


siae_signup_token_generator = SiaeSignupTokenGenerator()
