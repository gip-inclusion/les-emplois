from django.utils.module_loading import autodiscover_modules

from itou.job_applications.notifications import NewJobApplicationSiaeEmailNotification
from itou.utils.notifications.base_class import NotificationBase


#############################################################
################# DB DEFAULT JSON STRUCTURE #################
#############################################################

#####
##### 1/ Magically import any notification.
#####

# Find and load modules called "notifications" in Django apps.
autodiscover_modules("notifications")
# Then get a list of configured notifications throughout the project.
ALL_NOTIFICATIONS = NotificationBase.__subclasses__()


#####
##### 2/ Manually import class notifications and add
#####    them to the correct Database table field.
#####

SIAE_NOTIFICATIONS = [NewJobApplicationSiaeEmailNotification]
PRESCRIBER_NOTIFICATIONS = []
USER_NOTIFICATIONS = []


#####
##### 3/ Assert any notification existing in
#####    the project is referenced here.
#####

IMPORTED_NOTIFICATIONS = SIAE_NOTIFICATIONS + PRESCRIBER_NOTIFICATIONS + USER_NOTIFICATIONS
assert len(ALL_NOTIFICATIONS) == len(IMPORTED_NOTIFICATIONS)
assert IMPORTED_NOTIFICATIONS.sort() == ALL_NOTIFICATIONS.sort()


#####
##### 4/ Declare methods called on migrations.
#####


def default_notifications_dict(notifications_list):
    return {notification_class.__name__: {"subscribed": True} for notification_class in notifications_list}


def siaemembership_notifications_default():
    """
    Provide a default value to fill in the "notifications" field
    when a new SiaeMembership is created.
    """
    return default_notifications_dict(SIAE_NOTIFICATIONS)


def prescribermembership_notifications_default():
    """
    Provide a default value to fill in the "notifications" field
    when a new PrescriberMembership is created.
    """
    return default_notifications_dict(PRESCRIBER_NOTIFICATIONS)


def user_notifications_default():
    """
    Provide a default value to fill in the "notifications" field
    when a new User is created.
    """
    return default_notifications_dict(USER_NOTIFICATIONS)
