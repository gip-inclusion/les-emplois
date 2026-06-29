import datetime

from itou.recommendations.criteria import CriterionStatus, StructuredSolutionKind
from itou.recommendations.profile import DiagnosticConstraint
from itou.recommendations.rules import (
    AccompagnementIntensifRule,
    BoostInsertionRule,
    E2CRule,
    EARule,
    EPIDERule,
    FTEducationLevel,
    GEIQRule,
    PLIERule,
    PotentiellesRule,
    SIAERule,
    SkolaRule,
)
from tests.recommendations.factories import BeneficiaryProfileFactory, StructuredSolutionCandidateFactory


class TestPLIERule:
    rule = PLIERule()
    kind = StructuredSolutionKind.PLIE

    def _eligible_profile(self):
        return BeneficiaryProfileFactory(age=30, in_paris=True, is_qpv_resident=True)

    def test_eligible(self):
        result = self.rule.evaluate(
            self._eligible_profile(),
            StructuredSolutionCandidateFactory(kind=self.kind),
        )
        assert result.is_eligible

    def test_too_young(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=24, is_qpv_resident=True)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible

    def test_too_far(self):
        result = self.rule.evaluate(
            self._eligible_profile(),
            StructuredSolutionCandidateFactory(kind=self.kind, in_marseille=True),
        )
        assert not result.is_eligible

    def test_no_situation_criterion(self):
        profile = BeneficiaryProfileFactory(
            in_paris=True,
            age=30,
            is_qpv_resident=False,
            status_effective_date=datetime.date.today() - datetime.timedelta(days=30),
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible

    def test_unknown_coords_gives_unknown_distance(self):
        profile = BeneficiaryProfileFactory(age=30, is_qpv_resident=True)
        result = self.rule.evaluate(
            profile, StructuredSolutionCandidateFactory(kind=self.kind, without_coordinates=True)
        )
        distance_criterion = next(c for c in result.criteria if c.code == "distance")
        assert distance_criterion.status is CriterionStatus.UNKNOWN

    def test_inside_eligibility_zone(self):
        result = self.rule.evaluate(
            self._eligible_profile(),
            StructuredSolutionCandidateFactory(kind=self.kind, eligibility_zones=("75056",)),
        )
        assert result.is_eligible

    def test_outside_eligibility_zone(self):
        result = self.rule.evaluate(
            self._eligible_profile(),
            StructuredSolutionCandidateFactory(kind=self.kind, eligibility_zones=("93001",)),
        )
        zone_criterion = next(c for c in result.criteria if c.code == "zone_eligibilite")
        assert zone_criterion.status is CriterionStatus.NOT_MET
        assert not result.is_eligible


class TestEPIDERule:
    rule = EPIDERule()
    kind = StructuredSolutionKind.EPIDE

    def _eligible_profile(self):
        return BeneficiaryProfileFactory(
            age=20,
            in_paris=True,
            education_level=FTEducationLevel.CAP_BEP,
            is_registered_at_france_travail=True,
        )

    def test_eligible(self):
        result = self.rule.evaluate(
            self._eligible_profile(),
            StructuredSolutionCandidateFactory(kind=self.kind),
        )
        assert result.is_eligible

    def test_too_old(self):
        profile = BeneficiaryProfileFactory(
            age=26,
            in_paris=True,
            education_level=FTEducationLevel.CAP_BEP,
            is_registered_at_france_travail=True,
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible

    def test_within_100km(self):
        result = self.rule.evaluate(
            self._eligible_profile(),
            StructuredSolutionCandidateFactory(kind=self.kind, within_epide_range=True),
        )
        assert result.is_eligible


class TestE2CRule:
    rule = E2CRule()
    kind = StructuredSolutionKind.E2C

    def test_eligible_young(self):
        profile = BeneficiaryProfileFactory(
            in_paris=True,
            age=20,
            education_level=FTEducationLevel.CAP_BEP,
            is_registered_at_france_travail=True,
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_eligible_26_to_30_with_rqth(self):
        profile = BeneficiaryProfileFactory(
            in_paris=True,
            age=28,
            education_level=FTEducationLevel.CAP_BEP,
            is_registered_at_france_travail=True,
            is_rqth_beneficiary=True,
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_not_eligible_26_without_rqth(self):
        profile = BeneficiaryProfileFactory(
            in_paris=True,
            age=28,
            education_level=FTEducationLevel.CAP_BEP,
            is_registered_at_france_travail=True,
            is_rqth_beneficiary=False,
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible

    def test_not_eligible_too_old(self):
        profile = BeneficiaryProfileFactory(
            in_paris=True,
            age=31,
            education_level=FTEducationLevel.CAP_BEP,
            is_registered_at_france_travail=True,
            is_rqth_beneficiary=True,
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible


class TestAccompagnementIntensifRule:
    rule = AccompagnementIntensifRule()
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_ACCOMPAGNEMENT_INTENSIF

    def test_eligible(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=25, is_rsa_beneficiary=True)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_no_rsa(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=25, is_rsa_beneficiary=False)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible

    def test_too_old(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=31, is_rsa_beneficiary=True)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible


class TestSkolaRule:
    rule = SkolaRule()
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_SKOLA

    def test_eligible(self):
        profile = BeneficiaryProfileFactory(
            in_paris=True,
            age=22,
            education_level=FTEducationLevel.CAP_BEP,
            has_declared_constraints=True,
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible


class TestBoostInsertionRule:
    rule = BoostInsertionRule()
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_BOOST_INSERTION

    def test_eligible(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=25)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_too_old(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=30)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible


class TestPotentiellesRule:
    rule = PotentiellesRule()
    kind = StructuredSolutionKind.APPRENTIS_DAUTEUIL_POTENTIELLES

    def test_eligible_woman(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=25, civility="MME")
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_eligible_qpv(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=25, civility="M", is_qpv_resident=True)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_not_eligible_man_not_qpv(self):
        profile = BeneficiaryProfileFactory(in_paris=True, age=25, civility="M", is_qpv_resident=False)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible


class TestSIAERule:
    rule = SIAERule()
    kind = StructuredSolutionKind.SIAE

    def test_eligible_via_level1_rsa(self):
        profile = BeneficiaryProfileFactory(is_rsa_beneficiary=True)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_eligible_via_level1_detld(self):
        profile = BeneficiaryProfileFactory(status_effective_date=datetime.date.today() - datetime.timedelta(days=800))
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_eligible_via_3_level2_criteria(self):
        profile = BeneficiaryProfileFactory(
            age=22, education_level=FTEducationLevel.CAP_BEP, is_rqth_beneficiary=True, is_rsa_beneficiary=False
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_not_eligible_only_2_level2_criteria(self):
        profile = BeneficiaryProfileFactory(
            age=22,
            education_level=FTEducationLevel.CAP_BEP,
            is_rsa_beneficiary=False,
            is_rqth_beneficiary=False,
            is_qpv_resident=False,
            has_declared_constraints=True,
            diagnostic_constraints=(
                DiagnosticConstraint(code="20"),
                DiagnosticConstraint(code="6", impact="FORT"),
            ),
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible


class TestEARule:
    rule = EARule()
    kind = StructuredSolutionKind.EA

    def test_eligible(self):
        profile = BeneficiaryProfileFactory(is_rqth_beneficiary=True, education_level=FTEducationLevel.CAP_BEP)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible

    def test_not_eligible_without_rqth(self):
        profile = BeneficiaryProfileFactory(is_rqth_beneficiary=False, education_level=FTEducationLevel.CAP_BEP)
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible

    def test_not_eligible_rqth_but_no_additional_criterion(self):
        profile = BeneficiaryProfileFactory(
            is_rqth_beneficiary=True,
            is_rsa_beneficiary=False,
            education_level=FTEducationLevel.BAC_PLUS_5_AND_ABOVE,
            status_effective_date=datetime.date.today() - datetime.timedelta(days=30),
        )
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert not result.is_eligible


class TestGEIQRule:
    rule = GEIQRule()
    kind = StructuredSolutionKind.GEIQ

    def test_always_eligible(self):
        profile = BeneficiaryProfileFactory()
        result = self.rule.evaluate(profile, StructuredSolutionCandidateFactory(kind=self.kind))
        assert result.is_eligible
