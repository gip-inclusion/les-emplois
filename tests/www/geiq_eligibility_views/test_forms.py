import faker
import pytest

from itou.companies.enums import CompanyKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.www.geiq_eligibility_views.forms import GEIQAdministrativeCriteriaForGEIQForm, GEIQAdministrativeCriteriaForm
from tests.companies.factories import CompanyFactory


_FAKER = faker.Faker()


@pytest.fixture
def new_geiq():
    return CompanyFactory(kind=CompanyKind.GEIQ)


@pytest.fixture
def administrative_criteria_for_checkboxes():
    # Exclude hidden / children radio fields
    return [
        c for c in GEIQAdministrativeCriteria.objects.all() if c.key not in GEIQAdministrativeCriteriaForm.RADIO_FIELDS
    ]


@pytest.fixture
def criteria_with_parent():
    return GEIQAdministrativeCriteria.objects.filter(parent__isnull=False)


@pytest.fixture
def criteria_in_radio():
    return GEIQAdministrativeCriteria.objects.filter(slug__in=GEIQAdministrativeCriteriaForm.RADIO_FIELDS)


def test_init_geiq_administrative_criteria_form(new_geiq, administrative_criteria_for_checkboxes):
    # Mainly checks addition of htmx attributes
    for criterion in administrative_criteria_for_checkboxes:
        url = _FAKER.url()
        form = GEIQAdministrativeCriteriaForm(new_geiq, (), form_url=url, data={criterion.key: True})

        assert form.is_valid()
        assert "hx-post" in str(form[criterion.key])
        assert url in str(form[criterion.key])


def test_init_geiq_administrative_criteria_form_fields_with_parent(new_geiq, criteria_with_parent, criteria_in_radio):
    # Check that submitting a "child" without "parent" field enabled does nothing
    for criterion in criteria_with_parent:
        # This field has a nested radio field called "pole_emploi_related": pass, see below
        if criterion.parent.key == "personne_inscrite_a_pole_emploi":
            continue

        # Only child submitted is no go
        form = GEIQAdministrativeCriteriaForm(new_geiq, (), form_url=_FAKER.url(), data={criterion.key: True})

        assert form.is_valid()
        assert len(form.cleaned_data) == 0

        # Both parent and child is ok
        form = GEIQAdministrativeCriteriaForm(
            new_geiq, (), form_url=_FAKER.url(), data={criterion.key: True, criterion.parent.key: True}
        )

        assert form.is_valid()
        assert [criterion.parent.key, criterion.key] == list(map(lambda x: x.key, form.cleaned_data))

    # Check akward case of "pole_emploi_related" field: result of foldable radio set
    for criterion in criteria_in_radio:
        form = GEIQAdministrativeCriteriaForm(
            new_geiq, (), form_url=_FAKER.url(), data={"pole_emploi_related": criterion.pk}
        )

        assert form.is_valid()
        assert len(form.cleaned_data) == 0

        form = GEIQAdministrativeCriteriaForm(
            new_geiq,
            (),
            form_url=_FAKER.url(),
            data={"pole_emploi_related": criterion.pk, "personne_inscrite_a_pole_emploi": True},
        )

        assert form.is_valid()
        assert ["pole_emploi_related", "personne_inscrite_a_pole_emploi"] == list(
            map(lambda x: x.key, form.cleaned_data)
        )


def test_geiq_administrative_criteria_validation_for_geiq(new_geiq, administrative_criteria_for_checkboxes):
    url = _FAKER.url()
    form = GEIQAdministrativeCriteriaForGEIQForm(new_geiq, (), form_url=url, data={})

    # Field validation is the same as `GEIQAdministrativeCriteriaForm`
    # but in this case at least one field must be checked.
    # Already checked in `test_init_geiq_administrative_criteria_form`
    assert not form.is_valid()
    assert [["Vous devez saisir au moins un critère d'éligibilité GEIQ"]] == list(form.errors.values())

    for criterion in administrative_criteria_for_checkboxes:
        # Check CSS classes
        help_text = form.fields[criterion.key].help_text

        assert "mt-2 form-text text-muted fs-xs" in help_text or help_text == ""


def test_geiq_administrative_criteria_exclusions(new_geiq):
    # Checks deactivation of mutually excluded fields
    for field, exclusions in GEIQAdministrativeCriteriaForm.EXCLUSIONS.items():
        form = GEIQAdministrativeCriteriaForm(
            new_geiq, (), form_url="foo", accept_no_criteria=True, data={field: True}
        )

        assert form.is_valid()

        # A field can have multiple "exclusions"
        for disabled_field in exclusions:
            assert "disabled" in str(form[disabled_field])
