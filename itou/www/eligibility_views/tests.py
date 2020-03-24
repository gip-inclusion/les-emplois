from django.test import TestCase

from itou.eligibility.models import AdministrativeCriteria
from itou.www.eligibility_views.forms import AdministrativeCriteriaLevel1Form, AdministrativeCriteriaLevel2Form


class AdministrativeCriteriaLevel1FormTest(TestCase):
    def test_administrative_criteria_level1_form(self):
        form_data = {
            f"{AdministrativeCriteriaLevel1Form.FIELD_PREFIX}1": "true",
            f"{AdministrativeCriteriaLevel1Form.FIELD_PREFIX}2": "false",
            f"{AdministrativeCriteriaLevel1Form.FIELD_PREFIX}3": "true",
            f"{AdministrativeCriteriaLevel1Form.FIELD_PREFIX}4": "false",
        }
        form = AdministrativeCriteriaLevel1Form(data=form_data)
        form.is_valid()
        expected_cleaned_data = [AdministrativeCriteria.objects.get(pk=1), AdministrativeCriteria.objects.get(pk=3)]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_administrative_criteria_level2_form(self):
        form_data = {
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}5": "true",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}6": "false",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}7": "false",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}8": "false",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}9": "true",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}10": "false",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}11": "false",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}12": "false",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}13": "true",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}14": "true",
            f"{AdministrativeCriteriaLevel2Form.FIELD_PREFIX}15": "false",
        }
        form = AdministrativeCriteriaLevel2Form(data=form_data)
        form.is_valid()
        expected_cleaned_data = [
            AdministrativeCriteria.objects.get(pk=5),
            AdministrativeCriteria.objects.get(pk=9),
            AdministrativeCriteria.objects.get(pk=13),
            AdministrativeCriteria.objects.get(pk=14),
        ]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)
