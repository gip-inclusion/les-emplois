import sys

from django.conf import settings
from django.test import override_settings

from itou.utils.test import TestCase

from .testing import reload_module


SOME_VALUE = settings.SECRET_KEY  # is mandatory


class ReloadModuleTest(TestCase):
    def test_reload_module(self):
        current_module = sys.modules[__name__]
        self.assertEqual(current_module.SOME_VALUE, "foobar")

        with override_settings(SECRET_KEY="supermario"):
            with reload_module(current_module):
                self.assertEqual(current_module.SOME_VALUE, "supermario")
            self.assertEqual(current_module.SOME_VALUE, "foobar")
