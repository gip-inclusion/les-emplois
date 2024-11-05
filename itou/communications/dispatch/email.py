import logging

from itou.prescribers.models import PrescriberMembership
from itou.utils.emails import get_email_message

from .base import BaseNotification


logger = logging.getLogger(__name__)


class EmailNotification(BaseNotification):
    REQUIRED = BaseNotification.REQUIRED + ["subject_template", "body_template"]

    def build(self):
        # TODO: Temporary log for analysis : remove by the end of November 2024
        if self.user.is_prescriber and self.structure:
            memberships = (
                PrescriberMembership.objects.active().filter(organization=self.structure).select_related("user")
            )
            members = [m.user for m in memberships]
            if self.user not in members:
                admin_count = len([m for m in memberships if m.is_admin])
                logger.info("Estimate new email sent to admin_count=%d", admin_count)
        return get_email_message(
            [self.user.email],
            self.get_context(),
            self.subject_template,
            self.body_template,
        )

    def send(self):
        if self.should_send():
            return self.build().send()
