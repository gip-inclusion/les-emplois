from django.urls import reverse

from itou.utils.emails import get_email_message


class JobSeekerEmailFactory:
    def __init__(self, job_seeker):
        assert job_seeker.is_job_seeker
        self.job_seeker = job_seeker

    def info_about_upcoming_deletion(self, upcoming_deletion_date):
        context = {
            "job_seeker": self.job_seeker,
            "reset_password_url": reverse("account_reset_password"),
            "upcoming_deletion_date": upcoming_deletion_date,
        }
        subject = "users/email/job_seeker_upcoming_deletion_subject.txt"
        body = "users/email/job_seeker_upcoming_deletion_body.txt"
        return get_email_message([self.job_seeker.email], context, subject, body)

    def deletion_completed(self):
        context = {
            "job_seeker": self.job_seeker,
        }
        subject = "users/email/job_seeker_deletion_completed_subject.txt"
        body = "users/email/job_seeker_deletion_completed_body.txt"
        return get_email_message([self.job_seeker.email], context, subject, body)
