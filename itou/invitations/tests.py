from django.test import TestCase
from django.utils.http import urlsafe_base64_decode

from itou.invitations.factories import SentInvitationFactory
from itou.invitations.models import Invitation


class InvitationManagerTest(TestCase):
    def test_get_from_encoded_pk(self):
        invitation = SentInvitationFactory()
        self.assertEqual(Invitation.objects.get_from_encoded_pk(encoded_pk=invitation.encoded_pk).pk, invitation.pk)


class InvitationModelTest(TestCase):
    def setUp(self):
        self.invitation = SentInvitationFactory()

    def test_encoded_id(self):
        self.assertTrue(self.invitation.encoded_pk)
        decoded_pk = int(urlsafe_base64_decode(self.invitation.encoded_pk))
        self.assertEqual(self.invitation.pk, decoded_pk)

    def test_acceptance_link(self):
        self.assertIn(self.invitation.encoded_pk, self.invitation.acceptance_link)
