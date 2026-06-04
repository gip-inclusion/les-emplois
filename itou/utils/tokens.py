from datetime import datetime

from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.http import base36_to_int, int_to_base36


class TokenGenerator:
    """
    Base mixin for time-limited HMAC token generators.

    Subclasses must define:
    - key_salt (str)
    - timeout (int, seconds)
    - _make_hash_value(self, timestamp, **kwargs) -> str
    """

    secret = settings.SECRET_KEY

    def make_token(self, **kwargs):
        return self._make_token_with_timestamp(self._num_seconds(self._now()), **kwargs)

    def check_token(self, token, **kwargs):
        if not (token and all(kwargs.values())):
            return False
        try:
            timestamp_b36, _ = token.split("-")
        except ValueError:
            return False
        try:
            timestamp = base36_to_int(timestamp_b36)
        except ValueError:
            return False
        if not constant_time_compare(self._make_token_with_timestamp(timestamp, **kwargs), token):
            return False
        if (self._num_seconds(self._now()) - timestamp) > self.timeout:
            return False
        return True

    def _make_token_with_timestamp(self, timestamp, **kwargs):
        timestamp_b36 = int_to_base36(timestamp)
        hash_string = salted_hmac(
            self.key_salt, self._make_hash_value(timestamp, **kwargs), secret=self.secret
        ).hexdigest()[::2]
        return f"{timestamp_b36}-{hash_string}"

    def _num_seconds(self, dt):
        return int((dt - datetime(2001, 1, 1)).total_seconds())

    def _now(self):
        return datetime.now()


class CompanySignupTokenGenerator(TokenGenerator):
    """
    Strategy object used to generate and check tokens for the secure
    company signup mechanism.
    Heavily inspired from django PasswordResetTokenGenerator :
    https://github.com/django/django/blob/master/django/contrib/auth/tokens.py
    """

    key_salt = "itou.utils.tokens.SiaeSignupTokenGenerator"
    timeout = 2 * 7 * 24 * 3600

    def make_token(self, company):
        return super().make_token(company=company)

    def _make_hash_value(self, timestamp, company):
        """
        Hash the company's primary key and some company state (its number of members)
        that's sure to change after a signup to produce a token that is invalidated
        as soon as it is used.
        Moreover SIAE_SIGNUP_MAGIC_LINK_TIMEOUT eventually
        invalidates the token anyway.
        """
        return str(company.pk) + str(company.members.count()) + str(timestamp)


company_signup_token_generator = CompanySignupTokenGenerator()


class AdminRequestTokenGenerator(TokenGenerator):
    """
    Token generator for the admin role request mechanism.

    A member of a company with an auth_email can request the admin role.
    A token is generated and sent to auth_email. When the link is clicked,
    the token is validated and the member is promoted to admin.

    The token includes membership.is_admin in its hash so it is automatically
    invalidated once the promotion has been applied.
    """

    key_salt = "itou.utils.tokens.AdminRequestTokenGenerator"
    timeout = 2 * 7 * 24 * 3600

    def make_token(self, company, user):
        return super().make_token(company=company, user=user)

    def _make_hash_value(self, timestamp, company, user):
        membership = company.memberships.get(user=user)
        return f"{company.pk}{user.pk}{membership.is_admin}{timestamp}"


admin_request_token_generator = AdminRequestTokenGenerator()
