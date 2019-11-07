import json

from django.forms import ValidationError
from django.test import TestCase

from itou.eligibility.forms.form_v_1_0_0 import EligibilityForm
from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationWithMembershipFactory,
)
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import KIND_PRESCRIBER, KIND_SIAE_STAFF
from itou.utils.perms.user import UserInfo


class FormCleanSiaeTest(TestCase):
    """
    Test the clean algorithm for an SIAE staff member.
    """

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        cls.job_seeker = JobSeekerFactory()
        cls.siae = SiaeWithMembershipFactory()
        cls.user = cls.siae.members.first()
        cls.user_info = UserInfo(
            user=cls.user,
            kind=KIND_SIAE_STAFF,
            prescriber_organization=None,
            is_authorized_prescriber=False,
            siae=cls.siae,
        )

    def test_clean_siae_without_peripheral_barriers(self):
        data = {
            "criteres_administratifs_de_niveau_2": [
                "travailleur_handicape",
                "primo_arrivant",
            ]
        }
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        form.is_valid()
        with self.assertRaisesMessage(ValidationError, form.ERROR_PERIPHERAL_BARRIERS):
            form.clean()

    def test_clean_siae_without_administrative_criteria(self):
        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "connaitre_les_voies_de_recours_face_a_une_discrimination",
                "prendre_en_compte_une_problematique_judiciaire",
            ]
        }
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        form.is_valid()
        with self.assertRaisesMessage(
            ValidationError, form.ERROR_ADMINISTRATIVE_CRITERIA
        ):
            form.clean()

    def test_clean_siae_without_enough_administrative_criteria_level2(self):
        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "connaitre_les_voies_de_recours_face_a_une_discrimination",
                "prendre_en_compte_une_problematique_judiciaire",
            ],
            "criteres_administratifs_de_niveau_2": [
                "travailleur_handicape",
                "primo_arrivant",
            ],
        }
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        form.is_valid()
        with self.assertRaisesMessage(
            ValidationError, form.ERROR_ADMINISTRATIVE_CRITERIA_LEVEL2
        ):
            form.clean()

    def test_clean_siae_ok_1(self):
        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_1": ["beneficiaire_du_rsa"],
        }
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        self.assertTrue(form.is_valid())

    def test_clean_siae_ok_2(self):
        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_2": [
                "senior_50_ans",
                "travailleur_handicape",
                "primo_arrivant",
            ],
        }
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        self.assertTrue(form.is_valid())


class FormCleanAuthorizedPrescriberTest(TestCase):
    """
    Test the clean algorithm for an authorized prescriber.
    """

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        cls.job_seeker = JobSeekerFactory()
        cls.prescriber_organization = (
            AuthorizedPrescriberOrganizationWithMembershipFactory()
        )
        cls.user = cls.prescriber_organization.members.first()
        cls.user_info = UserInfo(
            user=cls.user,
            kind=KIND_PRESCRIBER,
            prescriber_organization=cls.prescriber_organization,
            is_authorized_prescriber=True,
            siae=None,
        )

    def test_clean_authorized_prescriber_without_peripheral_barriers(self):
        data = {}
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        form.is_valid()
        with self.assertRaisesMessage(ValidationError, form.ERROR_PERIPHERAL_BARRIERS):
            form.clean()

    def test_clean_authorized_prescriber_ok(self):
        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "connaitre_les_voies_de_recours_face_a_une_discrimination",
                "prendre_en_compte_une_problematique_judiciaire",
            ]
        }
        form = EligibilityForm(
            user_info=self.user_info, job_seeker=self.job_seeker, data=data
        )
        self.assertTrue(form.is_valid())


class FormGetHumanReadableDataTest(TestCase):
    def test_get_human_readable_data(self):

        job_seeker = JobSeekerFactory()
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        user_info = UserInfo(
            user=user,
            kind=KIND_SIAE_STAFF,
            prescriber_organization=None,
            is_authorized_prescriber=False,
            siae=siae,
        )

        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_2": [
                "senior_50_ans",
                "travailleur_handicape",
                "primo_arrivant",
            ],
        }
        form = EligibilityForm(user_info=user_info, job_seeker=job_seeker, data=data)
        self.assertTrue(form.is_valid())

        expected_data = {
            "Freins périphériques": [
                {
                    "Faire face à des difficultés administratives ou juridiques": [
                        "Prendre en compte une problématique judiciaire"
                    ]
                }
            ],
            "Critères administratifs": [
                {
                    "Critères administratifs de niveau 2": [
                        "Senior (+50 ans)",
                        "Travailleur handicapé",
                        "Primo arrivant",
                    ]
                }
            ],
        }
        self.assertEqual(form.get_human_readable_data(), expected_data)


class FormExtraInfoTest(TestCase):
    def test_extra_info(self):

        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_2": [
                "senior_50_ans",
                "travailleur_handicape",
                "primo_arrivant",
            ],
        }
        form = EligibilityForm(user_info=None, job_seeker=None, data=data)

        expected_data = {
            "value": "resident_zrr",
            "label": "Résident ZRR",
            "written_proof": "Justificatif de domicile",
            "help": "Zone de revitalisation rurale",
            "url": "https://www.data.gouv.fr/fr/datasets/zones-de-revitalisation-rurale-zrr/",
        }
        self.assertEqual(form.extra_info["resident_zrr"], expected_data)


class FormSaveTest(TestCase):
    def test_save_diagnosis(self):

        job_seeker = JobSeekerFactory()
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        user_info = UserInfo(
            user=user,
            kind=KIND_SIAE_STAFF,
            prescriber_organization=None,
            is_authorized_prescriber=False,
            siae=siae,
        )

        data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_2": [
                "senior_50_ans",
                "travailleur_handicape",
                "primo_arrivant",
            ],
        }
        form = EligibilityForm(user_info=user_info, job_seeker=job_seeker, data=data)
        self.assertTrue(form.is_valid())

        eligibility = form.save_diagnosis()
        self.assertEqual(eligibility.job_seeker, job_seeker)
        self.assertEqual(eligibility.author, user)
        self.assertEqual(eligibility.author_kind, KIND_SIAE_STAFF)
        self.assertEqual(eligibility.author_siae, siae)
        self.assertEqual(eligibility.author_prescriber_organization, None)
        self.assertEqual(eligibility.form_version, form.VERSION)
        self.assertEqual(eligibility.form_cleaned_data, json.dumps(form.cleaned_data))
        self.assertEqual(eligibility.data, json.dumps(form.get_human_readable_data()))
