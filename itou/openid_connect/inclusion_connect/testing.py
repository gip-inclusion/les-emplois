from django.test import TestCase, override_settings

from itou.utils.testing import reload_module

from . import constants


@override_settings(
    INCLUSION_CONNECT_BASE_URL="https://inclusion.connect.fake",
    INCLUSION_CONNECT_REALM="foobar",
    INCLUSION_CONNECT_CLIENT_ID="IC_CLIENT_ID_123",
    INCLUSION_CONNECT_CLIENT_SECRET="IC_CLIENT_SECRET_123",
)
@reload_module(constants)
class InclusionConnectBaseTestCase(TestCase):
    pass
