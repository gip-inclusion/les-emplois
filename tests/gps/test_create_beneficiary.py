from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.test import override_settings
from django.urls import resolve, reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertRedirects

from itou.asp.models import RSAAllocation
from itou.companies import enums as companies_enums
from itou.companies.models import Company
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import LackOfPoleEmploiId, UserKind
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.models import InclusiveDateRange
from tests.cities.factories import create_test_cities
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    JobSeekerWithAddressFactory,
    PrescriberFactory,
)


@pytest.mark.ignore_unknown_variable_template_error(
    "confirmation_needed", "job_seeker", "readonly_form", "update_job_seeker"
)
@override_settings(API_BAN_BASE_URL="http://ban-api")
@mock.patch(
    "itou.utils.apis.geocoding.get_geocoding_data",
    side_effect=mock_get_geocoding_data_by_ban_api_resolved,
)
def test_create_job_seeker(_mock, client):
    [city] = create_test_cities(["67"], num_per_department=1)
    singleton = Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)

    prescriber_organization = PrescriberOrganizationWithMembershipFactory(with_pending_authorization=True)
    user = prescriber_organization.members.first()
    client.force_login(user)

    dummy_job_seeker = JobSeekerWithAddressFactory.build(
        jobseeker_profile__with_hexa_address=True,
        jobseeker_profile__with_education_level=True,
        with_ban_geoloc_address=True,
    )

    response = client.get(reverse("dashboard:index"))

    apply_start_url = reverse("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true"

    response = client.get(apply_start_url)
    next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    assertRedirects(response, next_url)

    response = client.post(next_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "confirm": 1})

    job_seeker_session_name = str(resolve(response.url.replace("?gps=true", "")).kwargs["session_uuid"])
    next_url = (
        reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        )
        + "?gps=true"
    )
    assertRedirects(response, next_url)
    assert client.session[job_seeker_session_name] == {"profile": {"nir": dummy_job_seeker.jobseeker_profile.nir}}

    # Step get job seeker e-mail.
    # ----------------------------------------------------------------------

    response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

    job_seeker_session_name = str(resolve(response.url.replace("?gps=true", "")).kwargs["session_uuid"])
    expected_job_seeker_session = {
        "user": {
            "email": dummy_job_seeker.email,
        },
        "profile": {
            "nir": dummy_job_seeker.jobseeker_profile.nir,
        },
    }
    next_url = (
        reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        )
        + "?gps=true"
    )

    assertRedirects(response, next_url)
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    # Step create a job seeker.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    # The NIR is prefilled
    assertContains(response, dummy_job_seeker.jobseeker_profile.nir)
    # The back_url is correct
    assertContains(
        response,
        reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        ),
    )

    post_data = {
        "title": dummy_job_seeker.title,
        "first_name": dummy_job_seeker.first_name,
        "last_name": dummy_job_seeker.last_name,
        "birthdate": dummy_job_seeker.birthdate,
        "lack_of_nir": False,
        "lack_of_nir_reason": "",
    }
    response = client.post(next_url, data=post_data)
    expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
    expected_job_seeker_session["user"] |= post_data
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = (
        reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        )
        + "?gps=true"
    )
    assertRedirects(response, next_url)

    post_data = {
        "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
        "address_line_1": dummy_job_seeker.address_line_1,
        "post_code": city.post_codes[0],
        "insee_code": city.code_insee,
        "city": city.name,
        "phone": dummy_job_seeker.phone,
        "fill_mode": "ban_api",
    }

    response = client.post(next_url, data=post_data)

    expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = (
        reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        )
        + "?gps=true"
    )
    assertRedirects(response, next_url)

    post_data = {
        "education_level": dummy_job_seeker.jobseeker_profile.education_level,
    }
    response = client.post(next_url, data=post_data)
    expected_job_seeker_session["profile"] |= post_data | {
        "pole_emploi_id": "",
        "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
        "resourceless": False,
        "rqth_employee": False,
        "oeth_employee": False,
        "pole_emploi": False,
        "pole_emploi_id_forgotten": "",
        "pole_emploi_since": "",
        "unemployed": False,
        "unemployed_since": "",
        "rsa_allocation": False,
        "has_rsa_allocation": RSAAllocation.NO.value,
        "rsa_allocation_since": "",
        "ass_allocation": False,
        "ass_allocation_since": "",
        "aah_allocation": False,
        "aah_allocation_since": "",
    }
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = (
        reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        )
        + "?gps=true"
    )
    assertRedirects(response, next_url)

    response = client.get(next_url)
    assertContains(response, "Créer et suivre le bénéficiaire")

    response = client.post(next_url)
    assertRedirects(response, reverse("gps:my_groups"))
    created_job_seeker = User.objects.filter(kind=UserKind.JOB_SEEKER).select_related("follow_up_group").get()
    assert created_job_seeker.email == dummy_job_seeker.email
    assert list(created_job_seeker.follow_up_group.members.all()) == [user]


def test_gps_bypass(client):
    # The sender has a pending authorization, but we should be able to create the user anyway
    # Check that we are not redirected to apply:pending_authorization_for_sender"

    singleton = Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)

    prescriber_organization = PrescriberOrganizationWithMembershipFactory(with_pending_authorization=True)
    user = prescriber_organization.members.first()
    client.force_login(user)

    apply_start_url = reverse("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    response = client.get(apply_start_url)

    next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    assertRedirects(response, next_url)

    # SIAE has an active suspension, but we should be able to create the job_seeker for GPS
    company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
    Sanctions.objects.create(
        evaluated_siae=EvaluatedSiaeFactory(siae=company),
        suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
    )

    user = company.members.first()
    client.force_login(user)

    apply_start_url = reverse("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    response = client.get(apply_start_url)

    next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    assertRedirects(response, next_url)


@pytest.mark.ignore_unknown_variable_template_error("job_seeker")
def test_existing_user_with_email(client):
    """
    A user with the same email already exists, create the group with this user
    """
    singleton = Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)
    # Only authorized prescribers can add a NIR.
    # See User.can_add_nir
    prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
    user = prescriber_organization.members.first()
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="", with_pole_emploi_id=True)

    client.force_login(user)

    # Follow all redirections…
    response = client.get(reverse("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true", follow=True)

    # …until a job seeker has to be determined.
    assert response.status_code == 200
    last_url = response.redirect_chain[-1][0]
    assert last_url == reverse("apply:check_nir_for_sender", kwargs={"company_pk": singleton.pk}) + "?gps=true"

    # Enter a non-existing NIR.
    # ----------------------------------------------------------------------
    nir = "141068078200557"
    post_data = {"nir": nir, "confirm": 1}
    response = client.post(last_url, data=post_data)
    job_seeker_session_name = str(resolve(response.url.replace("?gps=true", "")).kwargs["session_uuid"])
    next_url = (
        reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": singleton.pk, "session_uuid": job_seeker_session_name},
        )
        + "?gps=true"
    )
    assert response.url == next_url
    assert client.session[job_seeker_session_name] == {"profile": {"nir": nir}}
    assertRedirects(response, next_url)

    # Enter an existing email.
    # ----------------------------------------------------------------------
    post_data = {"email": job_seeker.email, "preview": "1"}

    response = client.post(next_url, data=post_data)
    assert response.status_code == 200

    # Display GPS text in modal
    # ----------------------------------------------------------------------
    assertContains(response, "Si vous ne souhaitez pas suivre")

    post_data = {"email": job_seeker.email, "confirm": "1"}
    response = client.post(next_url, data=post_data)
    assertRedirects(response, reverse("gps:my_groups"))

    # Make sure the job seeker follow-up group was created
    # ----------------------------------------------------------------------
    job_seeker.refresh_from_db()
    assert job_seeker.follow_up_group is not None
    assert user in job_seeker.follow_up_group.members.all()


@pytest.mark.ignore_unknown_variable_template_error("job_seeker")
def test_existing_user_with_nir(client):
    """
    An user with the same NIR already exists, create the group with this user
    """
    singleton = Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)

    nir = "141068078200557"
    prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
    user = prescriber_organization.members.first()
    job_seeker = JobSeekerFactory(jobseeker_profile__nir=nir, with_pole_emploi_id=True)

    client.force_login(user)

    # Follow all redirections…
    response = client.get(reverse("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true", follow=True)

    # …until a job seeker has to be determined.
    assert response.status_code == 200
    last_url = response.redirect_chain[-1][0]
    assert last_url == reverse("apply:check_nir_for_sender", kwargs={"company_pk": singleton.pk}) + "?gps=true"

    # Enter an existing NIR.
    # ----------------------------------------------------------------------
    post_data = {"nir": nir, "preview": 1}
    response = client.post(last_url, data=post_data)

    assert response.status_code == 200
    assertContains(response, "Si ce n'est pas le bénéficiaire que vous souhaitez suivre")

    post_data = {"nir": nir, "confirm": 1}
    response = client.post(last_url, data=post_data)

    assertRedirects(response, reverse("gps:my_groups"))

    # Make sure the job seeker follow-up group was created
    # ----------------------------------------------------------------------
    job_seeker.refresh_from_db()
    assert job_seeker.follow_up_group is not None
    assert user in job_seeker.follow_up_group.members.all()


@pytest.mark.parametrize(
    "UserFactory, factory_args",
    [
        (PrescriberFactory, {"membership": True}),
        (PrescriberFactory, {"membership": False}),
        (EmployerFactory, {"with_company": True}),
    ],
)
def test_creation_by_user_kind(client, UserFactory, factory_args):
    singleton = Company.unfiltered_objects.get(siret=companies_enums.POLE_EMPLOI_SIRET)
    user = UserFactory(**factory_args)
    client.force_login(user)
    # Assert contains link.
    create_beneficiary_url = reverse("apply:start", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    response = client.get(reverse("gps:join_group"))
    assertContains(response, create_beneficiary_url)
    response = client.get(create_beneficiary_url)
    assert response.status_code == 302
    assert (
        response["Location"]
        == reverse("apply:check_nir_for_sender", kwargs={"company_pk": singleton.pk}) + "?gps=true"
    )
