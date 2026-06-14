import uuid

import pytest

from itou.recommendations import services
from itou.recommendations.enums import ProfileFlag
from itou.www.recommendations.enums import BeneficiaryOrder
from tests.recommendations.factories import BeneficiaryFactory
from tests.www.recommendations.conftest import OTHER_SAFIR, SAFIR


class TestBeneficiaryListForUser:
    def test_filters_by_referent_and_safir(self, advisor):
        user, org = advisor
        kept = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        BeneficiaryFactory(referent_email=user.email, organization_safir=OTHER_SAFIR)
        BeneficiaryFactory(referent_email="other@example.com", organization_safir=SAFIR)
        BeneficiaryFactory(referent_email="other@example.com", organization_safir=OTHER_SAFIR)

        result = services.get_beneficiaries_for_user(user=user, organization=org)
        assert [b.pk for b in result] == [kept.pk]

    @pytest.mark.parametrize(
        "order,expected_last_names",
        [
            (BeneficiaryOrder.FULL_NAME_ASC, ["Alpha", "Mike", "Zulu"]),
            (BeneficiaryOrder.FULL_NAME_DESC, ["Zulu", "Mike", "Alpha"]),
        ],
        ids=["asc", "desc"],
    )
    def test_order_full_name(self, advisor, order, expected_last_names):
        user, org = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        BeneficiaryFactory(last_name="Zulu", first_name="Z", **common)
        BeneficiaryFactory(last_name="Alpha", first_name="A", **common)
        BeneficiaryFactory(last_name="Mike", first_name="M", **common)
        result = services.get_beneficiaries_for_user(user=user, organization=org, order=order)
        assert [b.last_name for b in result] == expected_last_names

    def test_profile_kinds_filter_is_no_op_in_v1(self, advisor):
        """FIXME llalba: for now, every flag is True (`services.profile_flags`)."""
        user, org = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        BeneficiaryFactory(**common)
        BeneficiaryFactory(**common)

        result = services.get_beneficiaries_for_user(
            user=user, organization=org, profile_kinds=[ProfileFlag.RSA.value, ProfileFlag.QPV.value]
        )
        assert len(result) == 2

    def test_explicit_beneficiary_filter(self, advisor):
        user, org = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        kept = BeneficiaryFactory(**common)
        BeneficiaryFactory(**common)

        result = services.get_beneficiaries_for_user(user=user, organization=org, beneficiary=kept)
        assert [b.pk for b in result] == [kept.pk]


class TestBeneficiaryForUser:
    def test_returns_instance_when_in_scope(self, advisor):
        user, org = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        assert (
            services.get_beneficiary_for_user(public_id=beneficiary.public_id, user=user, organization=org)
            == beneficiary
        )

    def test_none_on_referent_mismatch(self, advisor):
        user, org = advisor
        beneficiary = BeneficiaryFactory(referent_email="other@example.com", organization_safir=SAFIR)
        assert services.get_beneficiary_for_user(public_id=beneficiary.public_id, user=user, organization=org) is None

    def test_none_on_safir_mismatch(self, advisor):
        user, org = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=OTHER_SAFIR)
        assert services.get_beneficiary_for_user(public_id=beneficiary.public_id, user=user, organization=org) is None

    def test_none_on_unknown_public_id(self, advisor):
        user, org = advisor
        assert services.get_beneficiary_for_user(public_id=uuid.uuid4(), user=user, organization=org) is None


class TestBeneficiaryAutocompleteSearch:
    def _in_scope(self, user, **kwargs):
        return BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR, **kwargs)

    def test_empty_term_returns_empty(self, advisor):
        user, org = advisor
        self._in_scope(user, first_name="Alice", last_name="Martin")
        assert services.beneficiary_autocomplete_search(user=user, organization=org, term="") == []
        assert services.beneficiary_autocomplete_search(user=user, organization=org, term="   ") == []

    def test_matches_first_name(self, advisor):
        user, org = advisor
        alice = self._in_scope(user, first_name="Alice", last_name="Martin")
        self._in_scope(user, first_name="Bob", last_name="Dupont")
        result = services.beneficiary_autocomplete_search(user=user, organization=org, term="Alice")
        assert [b.pk for b in result] == [alice.pk]

    def test_matches_last_name(self, advisor):
        user, org = advisor
        martin = self._in_scope(user, first_name="Alice", last_name="Martin")
        self._in_scope(user, first_name="Bob", last_name="Dupont")
        result = services.beneficiary_autocomplete_search(user=user, organization=org, term="Martin")
        assert [b.pk for b in result] == [martin.pk]

    def test_multi_term_requires_all_bits_to_match(self, advisor):
        user, org = advisor
        # Each bit must match at least one of (first_name, last_name).
        match = self._in_scope(user, first_name="Alice", last_name="Martin")
        self._in_scope(user, first_name="Alice", last_name="Dupont")
        self._in_scope(user, first_name="Bob", last_name="Martin")
        result = services.beneficiary_autocomplete_search(user=user, organization=org, term="Alice Martin")
        assert [b.pk for b in result] == [match.pk]

    def test_unaccent_matching(self, advisor):
        user, org = advisor
        martin = self._in_scope(user, first_name="Alice", last_name="Martín")
        result = services.beneficiary_autocomplete_search(user=user, organization=org, term="Martin")
        assert [b.pk for b in result] == [martin.pk]

    def test_respects_scope(self, advisor):
        user, org = advisor
        mine = self._in_scope(user, first_name="Alice", last_name="Martin")
        BeneficiaryFactory(
            first_name="Alice",
            last_name="Martin",
            referent_email="other@example.com",
            organization_safir=SAFIR,
        )
        BeneficiaryFactory(
            first_name="Alice",
            last_name="Martin",
            referent_email=user.email,
            organization_safir=OTHER_SAFIR,
        )
        result = services.beneficiary_autocomplete_search(user=user, organization=org, term="Martin")
        assert [b.pk for b in result] == [mine.pk]

    def test_limit_applied(self, advisor):
        user, org = advisor
        for i in range(25):
            self._in_scope(user, first_name=f"Person{i:02d}", last_name="Martin")
        result = services.beneficiary_autocomplete_search(user=user, organization=org, term="Martin", limit=20)
        assert len(result) == 20


class TestProfileHelpers:
    def test_profile_flags_returns_all_true(self):
        """FIXME llalba: for now, every flag is True (`services.profile_flags`)."""
        beneficiary = BeneficiaryFactory.build()
        flags = services.profile_flags(beneficiary)
        assert set(flags.keys()) == {flag.value for flag in ProfileFlag}
        assert all(flags.values())

    def test_profile_criteria_labels_is_ordered(self):
        all_flags = {flag.value: True for flag in ProfileFlag}
        labels = services.profile_criteria_labels(all_flags)
        # `_CRITERIA_ORDER` puts RSA first and OETH last.
        assert labels[0] == ProfileFlag.RSA.label
        assert labels[-1] == ProfileFlag.OETH.label

    def test_profile_criteria_labels_filters_inactive(self):
        only_rsa = {ProfileFlag.RSA.value: True}
        labels = services.profile_criteria_labels(only_rsa)
        assert labels == [ProfileFlag.RSA.label]


class TestMapPointsFor:
    def test_keeps_only_show_map_providers_and_promotes_kind_label(self):
        recommendations = [
            {
                "kind_label": "Formation",
                "providers": [
                    {"name": "Alpha", "address": "1 rue A", "lat": 45.0, "lon": 4.0, "show_map": True},
                    {"name": "Beta", "address": "2 rue B", "lat": 45.1, "lon": 4.1, "show_map": False},
                ],
            },
            {
                "kind_label": "Emploi",
                "providers": [
                    {"name": "Gamma", "address": "3 rue C", "lat": 46.0, "lon": 5.0, "show_map": True},
                ],
            },
        ]
        assert services.map_points_for(recommendations) == [
            {"name": "Alpha", "kind_label": "Formation", "address": "1 rue A", "lat": 45.0, "lon": 4.0},
            {"name": "Gamma", "kind_label": "Emploi", "address": "3 rue C", "lat": 46.0, "lon": 5.0},
        ]

    def test_empty_when_no_provider_is_shown(self):
        recommendations = [
            {
                "kind_label": "Formation",
                "providers": [{"name": "Alpha", "address": "a", "lat": 1.0, "lon": 2.0, "show_map": False}],
            },
        ]
        assert services.map_points_for(recommendations) == []
