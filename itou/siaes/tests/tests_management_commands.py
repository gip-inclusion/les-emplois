import datetime
import importlib
import shutil
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from itou.siaes.factories import SiaeConventionFactory, SiaeFactory
from itou.siaes.models import Siae


"""
   Function get_creatable_conventions() is not import in the header.
   Datasets have to be setup before its first call
"""


class ImportSiaeManagementCommandsTest(TestCase):

    path_dest = "./siaes/management/commands/data"
    path_source = "./siaes/fixtures"
    app_dir_path = Path((settings.APPS_DIR))
    mod = None

    @classmethod
    def setUpClass(cls):
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

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=Siae.KIND_ACI, convention=None)
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
        self.assertEqual((siae.source, siae.siret, siae.kind), (Siae.SOURCE_ASP, SIRET, Siae.KIND_ACI))
        self.assertTrue(True)

    def test_creatable_conventions_for_active_siae_where_siret_not_equals_siret_signature(self):
        SIRET = "34950857200055"
        SIRET_SIGNATURE = "34950857200048"
        ASP_ID = 768

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=Siae.KIND_AI, convention=None)
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
        self.assertEqual((siae.source, siae.siret, siae.kind), (Siae.SOURCE_ASP, SIRET, Siae.KIND_AI))

    def test_creatable_conventions_inactive_siae(self):
        SIRET = SIRET_SIGNATURE = "41294123900011"
        ASP_ID = 1780
        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=Siae.KIND_ACI, convention=None)
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
        self.assertEqual((siae.source, siae.siret, siae.kind), (Siae.SOURCE_ASP, SIRET, Siae.KIND_ACI))
