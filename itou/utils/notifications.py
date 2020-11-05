from django.db.models import Q

from itou.utils.emails import get_email_message


class NotificationBase:
    @property
    def class_name(self):
        return self.__class__.__name__

    @property
    def subscribed_lookup(self):
        """
        Return a Q object to be used in a queryset to get only subscribed members.
        For example: 
          Cls.objects.filter(self.subscribed_lookup)
        """
        filters = {f"notifications__{self.class_name}__subscribed": True}
        return Q(**filters)

    @property
    def email(self):
        raise NotImplementedError

    def send(self):
        return self.email.send()

    def unsubscribe(self, obj):
        """
        Prevent sending a notification to someone.
        `obj` should have a `notifications` field.
        """
        obj.notifications[self.class_name]["subscribed"] = False
        obj.save()

    def _get_recipients(self):
        """
        Override this method using `self.subscribed_lookup`.
        """
        raise NotImplementedError


##############################################################
######################## Load notifications ##################
##############################################################

######################## PROPOSAL 1 ##########################

from django.contrib.admin.sites import site
from django.utils.module_loading import autodiscover_modules


# Find and load modules called "notifications" in Django apps.
autodiscover_modules("notifications")

ALL_NOTIFICATIONS = NotificationBase.__subclasses__()


def notifications_default():
    """
    Provide a default value to fill in the "notifications" field.
    """
    return {notification_class.__name__: {"subscribed": True} for notification_class in ALL_NOTIFICATIONS}


####################### PROPOSAL 2 ############################
# I think it's the best one because it preserves our users repartition
# (job seekers, prescribers and siae staff) as it lets us "assign" notifications
# to the right user kind.

from itou.job_applications.notifications import NewJobApplicationSiaeEmailNotification


SIAE_NOTIFICATIONS = [NewJobApplicationSiaeEmailNotification]


def siaemembership_notifications_default():
    """
    Provide a default value to fill in the "notifications" field
    when a new SiaeMembership is created.
    """
    return {notification_class.__name__: {"subscribed": True} for notification_class in SIAE_NOTIFICATIONS}
