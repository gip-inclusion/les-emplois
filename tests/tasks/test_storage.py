import datetime
import threading
import unittest

import huey.constants
import pytest
from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase
from huey.tests.base import BaseTestCase
from huey.tests.test_storage import StorageTests

from itou.tasks.huey import DBConsumer, ItouHuey


TRANSACTIONAL_TEST_CASES = frozenset(["test_consumer_integration"])


class ItouHueyMixin:
    def get_test_name(self):
        return self.id().split(".")[-1]

    def get_huey(self):
        return ItouHuey("tests")


class TestFromHuey(ItouHueyMixin, StorageTests, BaseTestCase, TestCase):
    def setUp(self):
        if self.get_test_name() in TRANSACTIONAL_TEST_CASES:
            raise unittest.SkipTest("Requires a TransactionTestCase.")
        super().setUp()

    @pytest.mark.filterwarnings("ignore:Received naive datetime, interpreting in the current timezone:UserWarning")
    def test_schedule_methods(self):
        super().test_schedule_methods()


class TestFromHueyTransactional(ItouHueyMixin, StorageTests, BaseTestCase, TransactionTestCase):
    consumer_class = DBConsumer

    def setUp(self):
        if self.get_test_name() not in TRANSACTIONAL_TEST_CASES:
            raise unittest.SkipTest("Requires a TransactionTestCase.")
        super().setUp()

    @pytest.mark.filterwarnings("ignore:Received naive datetime, interpreting in the current timezone:UserWarning")
    def test_consumer_integration(self):
        super().test_consumer_integration()


def test_scheduler_naive_datetime_warnings():
    huey = ItouHuey("tests")
    now = datetime.datetime.now()
    msg_re = r"^Received naive datetime, interpreting in the current timezone\.$"
    with pytest.warns(UserWarning, match=msg_re):
        huey.storage.add_to_schedule(b"data", now)
    with pytest.warns(UserWarning, match=msg_re):
        huey.storage.read_schedule(now)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "arrange, act, empty_value",
    [
        pytest.param(
            lambda storage: storage.enqueue(b"data"),
            lambda storage: storage.dequeue(),
            None,
            id="dequeue",
        ),
        pytest.param(
            lambda storage: storage.add_to_schedule(b"data", datetime.datetime.now(tz=datetime.UTC)),
            lambda storage: storage.read_schedule(datetime.datetime.now(tz=datetime.UTC)),
            [],
            id="read_schedule",
        ),
        pytest.param(
            lambda storage: storage.put_data(b"key", b"data"),
            lambda storage: storage.pop_data(b"key"),
            huey.constants.EmptyData,
            id="pop_data",
        ),
        pytest.param(
            lambda storage: "",
            lambda storage: storage.put_if_empty(b"key", b"data"),
            False,
            id="put_if_empty",
        ),
    ],
)
def test_concurrency(arrange, act, empty_value):
    release_lock = threading.Event()
    ready = threading.Event()
    huey = ItouHuey("tests")
    arrange(huey.storage)

    def take_lock():
        huey = ItouHuey("tests")
        with transaction.atomic():
            act(huey.storage)
        ready.set()
        release_lock.wait(timeout=1)
        connections.close_all()

    t = threading.Thread(target=take_lock)
    t.start()
    ready.wait(timeout=1)
    try:
        value = act(huey.storage)  # Skipped locked row.
    finally:
        release_lock.set()
        t.join()

    assert value == empty_value
