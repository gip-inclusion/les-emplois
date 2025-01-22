import logging

from itou.communications.dispatch.base import BaseNotification
from itou.companies.models import CompanyMembership
from itou.prescribers.models import PrescriberMembership
from itou.utils.emails import get_email_message


logger = logging.getLogger(__name__)


class EmailNotification(BaseNotification):
    REQUIRED = BaseNotification.REQUIRED + ["subject_template", "body_template"]

    def build(self):
        return get_email_message(
            [self.user.email],
            self.get_context(),
            self.subject_template,
            self.body_template,
        )

    def send(self):
        if (
            # If it is already a forwarded notification, do not check if the user is still a member of the organization
            not self.forward_from_user
            # Don't use should_send() if the user left the org because we don't want to use his settings
            and self.is_applicable()
            and self.structure
            and (self.user.is_prescriber or self.user.is_employer)
        ):
            if self.user.is_prescriber:
                memberships = (
                    PrescriberMembership.objects.active().filter(organization=self.structure).select_related("user")
                )
            elif self.user.is_employer:
                memberships = CompanyMembership.objects.active().filter(company=self.structure).select_related("user")
            members = [m.user for m in memberships]
            if self.user not in members:
                admins = [m.user for m in memberships if m.is_admin]
                logger.info("Send email copy to admin, admin_count=%d", len(admins))
                for admin in admins:
                    self.__class__(admin, self.structure, self.user, **self.context).send()
        if self.should_send():
            self.build().send()
