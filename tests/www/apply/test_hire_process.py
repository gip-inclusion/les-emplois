import datetime

from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import (
    assertContains,
    assertRedirects,
    assertTemplateNotUsed,
    assertTemplateUsed,
)

from itou.asp.models import Commune
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication
from itou.utils.widgets import DuetDatePickerWidget
from tests.cities.factories import create_city_geispolsheim
from tests.companies.factories import (
    CompanyWithMembershipAndJobsFactory,
)
from tests.users.factories import (
    JobSeekerFactory,
)
from tests.www.apply.test_submit import fake_session_initialization


BACK_BUTTON_ARIA_LABEL = "Retourner à l’étape précédente"
LINK_RESET_MARKUP = (
    '<a href="%s" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"'
    ' aria-label="Annuler la saisie de ce formulaire">'
)


def test_hire_as_company(client):
    company = CompanyWithMembershipAndJobsFactory(romes=("N1101",))
    user = company.members.first()
    geispolsheim = create_city_geispolsheim()
    birthdate = datetime.date(1978, 12, 20)
    geispolsheim_commune_id = Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id
    job_seeker = JobSeekerFactory(
        jobseeker_profile__with_hexa_address=True,
        jobseeker_profile__with_education_level=True,
        with_ban_geoloc_address=True,
        jobseeker_profile__nir="178122978200508",
        jobseeker_profile__birthdate=birthdate,
        jobseeker_profile__birth_place_id=geispolsheim_commune_id,
        born_in_france=True,
        title="M",
    )
    apply_session = fake_session_initialization(client, company, job_seeker, {})
    # TODO: Use the new job_seeker view.
    url = reverse("apply:hire_confirmation", kwargs={"session_uuid": apply_session.name})
    client.force_login(user)
    response = client.get(url)
    assertTemplateNotUsed(response, "approvals/includes/box.html")
    assertContains(response, "Valider l’embauche")
    check_infos_url = reverse(
        "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": apply_session.name}
    )
    assertContains(
        response,
        f"""
        <a href="{check_infos_url}"
           class="btn btn-block btn-outline-primary"
           aria-label="{BACK_BUTTON_ARIA_LABEL}">
            <span>Retour</span>
        </a>
        """,
        html=True,
        count=1,
    )

    hiring_start_at = timezone.localdate()
    post_data = {
        "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        "hiring_end_at": "",
        "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
        "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        "answer": "",
        "ban_api_resolved_address": job_seeker.geocoding_address,
        "address_line_1": job_seeker.address_line_1,
        "post_code": geispolsheim.post_codes[0],
        "insee_code": geispolsheim.code_insee,
        "city": geispolsheim.name,
        "phone": job_seeker.phone,
        "fill_mode": "ban_api",
        # Select the first and only one option
        "address_for_autocomplete": "0",
        # BRSA criterion certification.
        "birthdate": job_seeker.jobseeker_profile.birthdate,
        "birth_place": job_seeker.jobseeker_profile.birth_place_id,
        "birth_country": job_seeker.jobseeker_profile.birth_country_id,
    }
    response = client.post(url, data=post_data, headers={"hx-request": "true"})
    assert response.status_code == 200
    assert response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
    post_data = post_data | {"confirmed": "True"}
    response = client.post(url, headers={"hx-request": "true"}, data=post_data)

    job_application = JobApplication.objects.get(sender=user, to_company=company)
    next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
    assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)

    assert job_application.job_seeker == job_seeker
    assert job_application.sender_kind == SenderKind.EMPLOYER
    assert job_application.sender_company == company
    assert job_application.sender_prescriber_organization is None
    assert job_application.state == JobApplicationState.ACCEPTED
    assert job_application.message == ""
    assert list(job_application.selected_jobs.all()) == []
    assert job_application.resume is None

    # Get application detail
    # ----------------------------------------------------------------------
    response = client.get(next_url)
    assertTemplateUsed(response, "approvals/includes/box.html")
    assert response.status_code == 200
