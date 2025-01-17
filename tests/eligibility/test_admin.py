from django.urls import reverse

from itou.eligibility.models.iae import AdministrativeCriteria
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory


def test_selected_criteria_inline(admin_client):
    diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.certifiable().first())
    certifiable = diagnosis.selected_administrative_criteria.get()
    certifiable.certified = True
    certifiable.save()
    diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.not_certifiable().first())
    not_certifiable = diagnosis.selected_administrative_criteria.exclude(pk=certifiable.pk).get()

    url = reverse("admin:eligibility_eligibilitydiagnosis_change", args=(diagnosis.pk,))
    post_data = {
        "author": diagnosis.author_id,
        "author_kind": diagnosis.author_kind,
        "job_seeker": diagnosis.job_seeker_id,
        "author_siae": diagnosis.author_siae_id,
        "selected_administrative_criteria-TOTAL_FORMS": "2",
        "selected_administrative_criteria-INITIAL_FORMS": "2",
        "selected_administrative_criteria-MIN_NUM_FORMS": "0",
        "selected_administrative_criteria-MAX_NUM_FORMS": "1000",
        "selected_administrative_criteria-0-id": certifiable.pk,
        "selected_administrative_criteria-0-eligibility_diagnosis": diagnosis.pk,
        "selected_administrative_criteria-1-id": not_certifiable.pk,
        "selected_administrative_criteria-1-eligibility_diagnosis": diagnosis.pk,
        "selected_administrative_criteria-__prefix__-id": "",
        "selected_administrative_criteria-__prefix__-eligibility_diagnosis": "1100350",
        "jobapplication_set-TOTAL_FORMS": "0",
        "jobapplication_set-INITIAL_FORMS": "0",
        "jobapplication_set-MIN_NUM_FORMS": "0",
        "jobapplication_set-MAX_NUM_FORMS": "0",
        "approval_set-TOTAL_FORMS": "0",
        "approval_set-INITIAL_FORMS": "0",
        "approval_set-MIN_NUM_FORMS": "0",
        "approval_set-MAX_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
        "_save": "Enregistrer",
    }

    response = admin_client.post(url, data=post_data | {"selected_administrative_criteria-0-DELETE": "on"})
    assert response.status_code == 200
    assert response.context["errors"] == ["Impossible de supprimer un critère certifié"]
    diagnosis.refresh_from_db()
    assert diagnosis.administrative_criteria.count() == 2

    response = admin_client.post(url, data=post_data | {"selected_administrative_criteria-1-DELETE": "on"})
    assert response.status_code == 302  # it worked and we were redirected to the changelist
    diagnosis.refresh_from_db()
    assert diagnosis.administrative_criteria.count() == 1
