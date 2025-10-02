from django.conf import settings


def show_afpa_ad(user):
    return user.job_seeker_department in settings.AFPA_DEPARTMENTS
