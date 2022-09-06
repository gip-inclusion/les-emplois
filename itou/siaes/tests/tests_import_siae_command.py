import datetime
import importlib
import os
import shutil
import unittest
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.test import TransactionTestCase
from django.urls import reverse

from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeConventionFactory, SiaeFactory, SiaeWith2MembershipsFactory
from itou.siaes.models import Siae


def set_inactive(membership):
    """
    Helper used to set the membership inactive in the "has_members" meaning,
    see organization abstract models for details.
    """
    user = membership.user
    user.is_active = False
    user.save(update_fields=["is_active"])
    membership.is_active = False
    membership.save(update_fields=["is_active"])


def lazy_import_siae_command():
    # Has to be lazy-loaded to benefit from the file mock, this management command does crazy stuff at import.
    from itou.siaes.management.commands import import_siae

    instance = import_siae.Command()
    # Required otherwise the variable is undefined and throws an exception when incrementend the first time.
    instance.fatal_errors = 0
    return instance


@unittest.skipUnless(
    os.getenv("CI", "False"), "Slow and scarcely updated management command, no need for constant testing!"
)
class ImportSiaeManagementCommandsTest(TransactionTestCase):

    path_dest = "./siaes/management/commands/data"
    path_source = "./siaes/fixtures"
    app_dir_path = Path((settings.APPS_DIR))
    mod = None

    @classmethod
    def setUpClass(cls):
        """We need to setup fake files before loading any `import_siae` related script,
        since it does rely on dynamic file loading upon startup (!)
        """
        # copying datasets from fixtures dir
        files = [x for x in cls.app_dir_path.joinpath(cls.path_source).glob("fluxIAE_*.csv.gz") if x.is_file()]
        cls.app_dir_path.joinpath(cls.path_dest).mkdir(parents=True, exist_ok=True)
        for file in files:
            shutil.copy(file, cls.app_dir_path.joinpath(cls.path_dest))

        cls.mod = importlib.import_module("itou.siaes.management.commands._import_siae.convention")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.app_dir_path.joinpath(cls.path_dest))
        cls.mod = None

    def test_uncreatable_conventions_for_active_siae_with_active_convention(self):
        siae = SiaeFactory(source=Siae.SOURCE_ASP)
        self.assertTrue(siae.is_active)
        self.assertFalse(self.mod.get_creatable_conventions())

    def test_uncreatable_conventions_when_convention_exists_for_asp_id_and_kind(self):
        # siae without convention, but a convention already exists for this
        # asp_id and this kind. ACHTUNG: asp_id is collected from vue_structure_df :D
        SIRET = "26290411300061"
        ASP_ID = 190

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, convention=None)
        SiaeConventionFactory(kind=siae.kind, asp_id=ASP_ID)

        with self.assertRaises(AssertionError):
            self.mod.get_creatable_conventions()

    def test_creatable_conventions_for_active_siae_where_siret_equals_siret_signature(self):
        SIRET = SIRET_SIGNATURE = "21540323900019"
        ASP_ID = 112

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.ACI, convention=None)
        results = self.mod.get_creatable_conventions()

        self.assertEqual(len(results), 1)

        convention, siae = results[0]
        self.assertEqual(
            (
                convention.asp_id,
                convention.kind,
                convention.siret_signature,
                convention.is_active,
                convention.deactivated_at,
            ),
            (ASP_ID, siae.kind, SIRET_SIGNATURE, True, None),
        )
        self.assertEqual((siae.source, siae.siret, siae.kind), (Siae.SOURCE_ASP, SIRET, SiaeKind.ACI))

    def test_creatable_conventions_for_active_siae_where_siret_not_equals_siret_signature(self):
        SIRET = "34950857200055"
        SIRET_SIGNATURE = "34950857200048"
        ASP_ID = 768

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.AI, convention=None)
        results = self.mod.get_creatable_conventions()

        self.assertEqual(len(results), 1)

        convention, siae = results[0]
        self.assertEqual(
            (
                convention.asp_id,
                convention.kind,
                convention.siret_signature,
                convention.is_active,
                convention.deactivated_at,
            ),
            (ASP_ID, siae.kind, SIRET_SIGNATURE, True, None),
        )
        self.assertEqual((siae.source, siae.siret, siae.kind), (Siae.SOURCE_ASP, SIRET, SiaeKind.AI))

    def test_creatable_conventions_inactive_siae(self):
        SIRET = SIRET_SIGNATURE = "41294123900011"
        ASP_ID = 1780
        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.ACI, convention=None)
        results = self.mod.get_creatable_conventions()

        self.assertEqual(len(results), 1)

        convention, siae = results[0]
        self.assertEqual(
            (
                convention.asp_id,
                convention.kind,
                convention.siret_signature,
                convention.is_active,
                convention.deactivated_at.to_pydatetime(),
            ),
            (ASP_ID, siae.kind, SIRET_SIGNATURE, False, datetime.datetime(2020, 2, 29, 0, 0)),
        )
        self.assertEqual((siae.source, siae.siret, siae.kind), (Siae.SOURCE_ASP, SIRET, SiaeKind.ACI))

    def test_check_convention_data_consistency_aciphc_edge_case(self):
        SIRET = "41294123900011"
        user_created_siae = SiaeFactory(
            siret=SIRET,
            kind=SiaeKind.ACIPHC,
            source=Siae.SOURCE_USER_CREATED,
            convention__siret_signature=SIRET,
            convention__kind=SiaeKind.ACI,
        )
        SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.ACI, convention=user_created_siae.convention)
        self.mod.check_convention_data_consistency()

    def test_check_signup_possible_for_a_siae_without_members_but_with_auth_email(self):
        instance = lazy_import_siae_command()
        SiaeFactory(auth_email="tadaaa")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        self.assertEqual(instance.fatal_errors, 0)

    def test_check_signup_possible_for_a_siae_without_members_nor_auth_email(self):
        instance = lazy_import_siae_command()
        SiaeFactory(auth_email="")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        self.assertEqual(instance.fatal_errors, 1)

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_one(self):
        instance = lazy_import_siae_command()
        siae = SiaeWith2MembershipsFactory(auth_email="")
        members = siae.siaemembership_set.all()
        set_inactive(members[0])  # the other member is still active
        siae.siaemembership_set.set(members)

        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        self.assertEqual(instance.fatal_errors, 0)

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_two(self):
        instance = lazy_import_siae_command()
        siae = SiaeWith2MembershipsFactory(auth_email="")
        members = siae.siaemembership_set.all()
        set_inactive(members[0])
        set_inactive(members[1])
        siae.siaemembership_set.set([members[0], members[1]])
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        self.assertEqual(instance.fatal_errors, 1)

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_three(self):
        instance = lazy_import_siae_command()
        SiaeWith2MembershipsFactory(auth_email="")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        self.assertEqual(instance.fatal_errors, 0)

    def test_activate_your_account_email_for_a_siae_without_members_but_with_auth_email(self):
        instance = lazy_import_siae_command()
        instance.create_new_siaes()
        self.assertIn(reverse("signup:siae_select"), mail.outbox[0].body)
        self.assertEqual(
            [
                f"Activez le compte de votre {kind} {name} sur les emplois de l'inclusion"
                for (kind, name) in Siae.objects.values_list("kind", "name")
            ],
            [mail.subject for mail in mail.outbox],
        )
