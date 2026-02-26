from django.test import TestCase
from huey.tests.base import BaseTestCase
from huey.tests.test_storage import StorageTests

from itou.tasks.huey import ItouHuey


class TestFromHuey(StorageTests, BaseTestCase, TestCase):
    def get_huey(self):
        return ItouHuey("tests")
