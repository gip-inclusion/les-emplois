from itou.communications.dispatch.base import BaseNotification


class FakeNotificationClassesMixin:
    def setUp(self):
        class TestNotification(BaseNotification):
            pass

        class TestOtherNotification(BaseNotification):
            REQUIRED = BaseNotification.REQUIRED + ["required_attribute"]

        self.TestNotification = TestNotification
        self.TestOtherNotification = TestOtherNotification
