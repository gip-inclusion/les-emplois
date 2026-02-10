import datetime

from django.utils import timezone

from itou.geiq_assessments.models import AssessmentCampaign


def update_campaign_dates():
    """
    Dynamically set current campaign's year to last year to be able to create assessments.
    """
    now = timezone.now()
    year = now.year - 1
    submission_deadline = now.date() + datetime.timedelta(days=30)
    review_deadline = now.date() + datetime.timedelta(days=30 * 2)

    AssessmentCampaign.objects.filter(pk=1).update(
        year=year, submission_deadline=submission_deadline, review_deadline=review_deadline
    )
