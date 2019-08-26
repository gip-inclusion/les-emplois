from django.test import TestCase
from django.core import mail

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.job_applications.factories import JobRequestFactory


# from itou.prescribers.factories import PrescriberWithMembershipFactory
# p = PrescriberWithMembershipFactory()
# print("-" * 80)
# print(p)
# print(p.members.first())


class JobRequestModelStateWorkflowTest(TestCase):
    def test_job_request(self):

        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_request = JobRequestFactory(jobs=Appellation.objects.all())

        # print("-" * 80)
        # print(job_request.id)
        # print(job_request.job_seeker)

        # print("-" * 80)
        # print(job_request.jobs.all())

        # print("-" * 40)
        # print(job_request.state)
        # print(job_request.get_state_display())

        # print("-" * 40)
        # print(job_request.state.is_new)
        # print(job_request.state.is_pending_answer)
        # print(job_request.state.is_accepted)
        # print(job_request.state.is_rejected)
        # print(job_request.state.is_obsolete)

        job_request.send()

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]

        print("-" * 80)
        print(email.subject)
        print(email.body)
