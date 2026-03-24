import datetime
import random
import uuid

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db.models import Q
from django.urls import resolve, reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import escape
from django.utils.timezone import localtime
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from itoutils.urls import add_url_params
from pytest_django.asserts import (
    assertContains,
    assertFormError,
    assertMessages,
    assertNotContains,
    assertRedirects,
    assertTemplateNotUsed,
    assertTemplateUsed,
)

from itou.asp.models import AllocationDuration, Commune, Country, EducationLevel, RSAAllocation
from itou.companies.enums import CompanyKind, ContractType
from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.eligibility.models import (
    AdministrativeCriteria,
    EligibilityDiagnosis,
    GEIQAdministrativeCriteria,
    GEIQEligibilityDiagnosis,
)
from itou.job_applications.enums import JobApplicationState, QualificationLevel, QualificationType, SenderKind
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import ActionKind, IdentityCertificationAuthorities, LackOfNIRReason, LackOfPoleEmploiId
from itou.users.models import IdentityCertification, JobSeekerAssignment, JobSeekerProfile, User
from itou.utils.mocks.address_format import mock_get_first_geocoding_data, mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.models import InclusiveDateRange
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.views.hire_views import HIRE_SESSION_KIND, initialize_hire_session
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.approvals.factories import ApprovalFactory
from tests.cities.factories import create_city_geispolsheim
from tests.companies.factories import (
    CompanyFactory,
    JobDescriptionFactory,
    SiaeConventionFactory,
)
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.users.test_models import user_with_approval_in_waiting_period
from tests.utils.testing import get_session_name, parse_response_to_soup, pretty_indented
from tests.www.apply.test_submit import (
    UpdateJobSeekerTestMixin,
    assert_contains_apply_email_modal,
    assert_contains_apply_nir_modal,
)


LINK_RESET_MARKUP = (
    '<a href="%s" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"'
    ' aria-label="Annuler la saisie de ce formulaire">'
)
CONFIRM_RESET_MARKUP = '<a href="%s" class="btn btn-sm btn-danger">Confirmer l\'annulation</a>'
CONFIRM_BUTTON_MARKUP = (
    '<button type="submit" class="btn btn-block btn-primary" aria-label="Confirmer l’embauche de %s">'
    "<span>Confirmer l’embauche</span>"
    "</button>"
)
NEXT_BUTTON_MARKUP = (
    '<button type="submit" class="btn btn-block btn-primary" aria-label="Passer à l’étape suivante">'
    "<span>Suivant</span>"
    "</button>"
)


def fake_session_initialization(client, company, job_seeker, data):
    data.setdefault("reset_url", reverse("dashboard:index"))
    data.setdefault("company_pk", company.pk)
    if job_seeker:
        data["job_seeker_public_id"] = str(job_seeker.public_id)
    # The first argument is supposed to be a request, but we only need it to have a session attribute so client works
    session = initialize_hire_session(client, data)
    session.save()
    return session


class TestHire:
    def test_anonymous_access(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        url = reverse("apply:start_hire", kwargs={"company_pk": company.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

        job_seeker = JobSeekerFactory()
        hire_session = fake_session_initialization(client, company, job_seeker, {})
        for viewname in (
            "job_seekers_views:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:iae_eligibility_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:hire_fill_job_seeker_infos",
            "apply:hire_contract_infos",
        ):
            url = reverse(viewname, kwargs={"session_uuid": hire_session.name})
            response = client.get(url)
            assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_we_raise_a_404_on_missing_session(self, client):
        user = JobSeekerFactory()
        client.force_login(user)

        response = client.get(
            reverse(
                "job_seekers_views:search_by_email_for_hire",
                kwargs={"session_uuid": str(uuid.uuid4())},
            )
        )
        assert response.status_code == 404

    def test_we_raise_a_404_on_missing_temporary_session_for_create_job_seeker(self, client, subtests):
        routes = {
            "job_seekers_views:create_job_seeker_step_1_for_hire",
            "job_seekers_views:create_job_seeker_step_2_for_hire",
            "job_seekers_views:create_job_seeker_step_3_for_hire",
            "job_seekers_views:create_job_seeker_step_end_for_hire",
        }
        user = JobSeekerFactory()

        client.force_login(user)
        for route in routes:
            with subtests.test(route=route):
                response = client.get(reverse(route, kwargs={"session_uuid": uuid.uuid4()}))
                assert response.status_code == 404

    def test_404_when_trying_to_update_a_prescriber(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        prescriber = PrescriberFactory()
        client.force_login(company.members.first())
        params = {
            "job_seeker_public_id": prescriber.public_id,
            "from_url": reverse("dashboard:index"),
        }
        url = reverse("job_seekers_views:update_job_seeker_start", query=params)
        response = client.get(url)
        assert response.status_code == 404

    def test_404_when_trying_to_hire_a_prescriber(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        prescriber = PrescriberFactory()
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, prescriber, {})
        for viewname in (
            "job_seekers_views:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:iae_eligibility_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:hire_fill_job_seeker_infos",
            "apply:hire_contract_infos",
        ):
            url = reverse(viewname, kwargs={"session_uuid": hire_session.name})
            response = client.get(url)
            assert response.status_code == 404

    def test_403_when_trying_to_hire_a_jobseeker_with_invalid_approval(self, client):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        job_seeker = user_with_approval_in_waiting_period()
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, job_seeker, {})
        for viewname in (
            "job_seekers_views:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:iae_eligibility_for_hire",
            "apply:hire_fill_job_seeker_infos",
            "apply:hire_contract_infos",
        ):
            url = reverse(viewname, kwargs={"session_uuid": hire_session.name})
            response = client.get(url)
            assertContains(response, "Le candidat a terminé un parcours il y a moins de deux ans", status_code=403)

    @pytest.mark.parametrize(
        "back_url,expected_session",
        [
            pytest.param("/une/url/quelconque", {"reset_url": "/une/url/quelconque"}, id="with_back_url"),
            pytest.param("", {"reset_url": reverse("dashboard:index")}, id="empty"),
        ],
    )
    def test_start_view_initializes_session(self, client, back_url, expected_session):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        client.force_login(company.members.first())
        url = reverse("apply:start_hire", kwargs={"company_pk": company.pk})
        client.get(url, {"back_url": back_url})

        assert get_session_name(client.session, HIRE_SESSION_KIND) is not None


class TestDirectHireFullProcess:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def test_perms_for_company(self, client):
        """A company can hire only for itself."""
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)

        user = company_1.members.first()
        client.force_login(user)

        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": company_2.pk}))
        assert response.status_code == 403

    def test_hire_as_siae_with_suspension_sanction(self, client):
        company = CompanyFactory(
            romes=("N1101", "N1105"), with_membership=True, with_jobs=True, subject_to_iae_rules=True
        )
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        job_seeker = JobSeekerFactory(
            # Avoid redirect to fill user infos
            jobseeker_profile__with_pole_emploi_id=True,
            with_address=True,
            born_in_france=True,
        )
        user = company.members.first()
        client.force_login(user)
        hire_session = fake_session_initialization(
            client,
            company,
            job_seeker,
            {"selected_jobs": [], "contract_form_data": {"hiring_start_at": timezone.localdate()}},
        )

        response = client.get(reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertContains(
            response,
            "suite aux mesures prises dans le cadre du contrôle a posteriori",
            status_code=403,
        )

    @freeze_time("2025-08-22")
    def test_hire_as_company(self, client, snapshot):
        """Apply as company (and create new job seeker)"""

        company = CompanyFactory(
            romes=("N1101", "N1105"), with_membership=True, with_jobs=True, subject_to_iae_rules=True
        )
        reset_url_dashboard = reverse("dashboard:index")

        user = company.members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            jobseeker_profile__education_level=EducationLevel.BAC_LEVEL,
            email="johannes@brahms.com",
            phone="0123456789",
            title="M",
            last_checked_at=timezone.make_aware(datetime.datetime(2023, 10, 1, 12, 0, 0)),
            first_name="Johannes",
            last_name="Brahms",
        )
        existing_job_seeker = JobSeekerFactory()

        geispolsheim = create_city_geispolsheim()

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": company.pk}), follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        hire_session_name = get_session_name(client.session, HIRE_SESSION_KIND)
        check_nir_url = reverse(
            "job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Step determine the job seeker with a NIR. First try: NIR is found
        # ----------------------------------------------------------------------

        response = client.get(check_nir_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_dashboard)

        response = client.post(check_nir_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, existing_job_seeker)

        # Step determine the job seeker with a NIR. Second try: NIR is not found
        # ----------------------------------------------------------------------

        response = client.post(check_nir_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step get job seeker e-mail. First try: email is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        response = client.post(
            next_url,
            data={"email": existing_job_seeker.email, "preview": 1},
        )

        assert_contains_apply_email_modal(response, existing_job_seeker)

        # Step get job seeker e-mail. Second try: email is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session = {
            "config": {
                "tunnel": "hire",
                "from_url": reset_url_dashboard,
            },
            "apply": {
                "company_pk": company.pk,
                "session_uuid": hire_session_name,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        # The NIR is prefilled
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)
        # Check that the back url is correct
        assertContains(
            response,
            reverse(
                "job_seekers_views:search_by_email_for_hire",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        # Let's check for consistency between the NIR, the birthdate and the title.
        # ----------------------------------------------------------------------

        post_data = {
            "title": "MME",  # inconsistent title
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
            "birth_country": Country.FRANCE_ID,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_TITLE % "")

        post_data = {
            "title": "M",
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")

        # Resume to valid data and proceed with "normal" flow.
        # ----------------------------------------------------------------------

        birth_place_id = Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id
        birth_country_id = Country.FRANCE_ID
        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": birth_place_id,
            "birth_country": birth_country_id,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": geispolsheim.post_codes[0],
            "insee_code": geispolsheim.code_insee,
            "city": geispolsheim.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        response = client.post(next_url, data=post_data)

        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

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
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)
        soup = parse_response_to_soup(response, selector=".personal-infos")
        assert pretty_indented(soup) == snapshot(name="personal-infos")

        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert new_job_seeker.jobseeker_profile.nir

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            company=company,
            last_action_kind=ActionKind.CREATE,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        fill_job_seeker_infos_url = reverse(
            "apply:hire_fill_job_seeker_infos",
            kwargs={"session_uuid": hire_session_name},
            query={"job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)

        # Fill job seeker infos
        # ----------------------------------------------------------------------
        response = client.get(fill_job_seeker_infos_url)
        # No missing data to fill - skip to contract
        contract_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session_name})
        assertRedirects(response, contract_url)

        check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session_name}
        )

        # Contract infos
        # ----------------------------------------------------------------------
        response = client.get(contract_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)
        assertContains(response, check_infos_url)  # Back button URL

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
        }
        response = client.post(contract_url, data=post_data)
        next_url = reverse(
            "apply:iae_eligibility_for_hire",
            kwargs={"session_uuid": hire_session_name},
        )
        assertRedirects(response, next_url)

        # Step eligibility diagnosis
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")

        criterion1 = (
            AdministrativeCriteria.objects.level1().exclude(kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS).first()
        )
        [criterion2, criterion3] = AdministrativeCriteria.objects.level2().exclude(
            kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS
        )[:2]
        response = client.post(
            next_url,
            data={
                # Administrative criteria level 1.
                f"{criterion1.key}": "on",
                # Administrative criteria level 2.
                f"{criterion2.key}": "on",
                f"{criterion3.key}": "on",
            },
        )

        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session_name})
        assertRedirects(response, confirmation_url, fetch_redirect_response=False)
        diag = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=new_job_seeker, for_siae=company)
        assert diag.expires_at == timezone.localdate() + EligibilityDiagnosis.EMPLOYER_DIAGNOSIS_VALIDITY_TIMEDELTA

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            company=company,
            last_action_kind=ActionKind.IAE_ELIGIBILITY,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        # Confirmation
        # ----------------------------------------------------------------------
        response = client.get(confirmation_url)
        assertContains(response, CONFIRM_BUTTON_MARKUP % new_job_seeker.get_inverted_full_name(), html=True)
        assertContains(response, contract_url)  # Back button URL
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)

        job_application = JobApplication.objects.select_related("job_seeker__jobseeker_profile").get(
            sender=user, to_company=company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url, fetch_redirect_response=False)

        assert job_application.job_seeker == new_job_seeker
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
        assertTemplateUsed(response, "utils/templatetags/approval_box.html")
        assert response.status_code == 200

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assert JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            company=company,
            last_action_kind=ActionKind.HIRE,
        ).exists()

    @freeze_time()
    def test_hire_as_geiq(self, client, mocker, settings):
        """Apply as GEIQ with pre-existing job seeker without previous application"""
        company = CompanyFactory(romes=("N1101", "N1105"), kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        reset_url_dashboard = reverse("dashboard:index")
        job_seeker = JobSeekerFactory(born_outside_france=True)
        geispolsheim = create_city_geispolsheim()
        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

        user = company.members.first()
        client.force_login(user)

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": company.pk}), follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        hire_session_name = get_session_name(client.session, HIRE_SESSION_KIND)
        check_nir_url = reverse(
            "job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Step determine the job seeker with a NIR. First: show modal
        # ----------------------------------------------------------------------
        response = client.get(check_nir_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_dashboard)

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, job_seeker)

        # Step determine the job seeker with a NIR. Second: confirm
        # ----------------------------------------------------------------------

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": 1})
        check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session_name}
        )
        next_url = add_url_params(
            check_infos_url,
            {"job_seeker_public_id": job_seeker.public_id},
        )
        assertRedirects(response, next_url, fetch_redirect_response=False)

        # Step check job seeker infos
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")

        prev_applicaitons_url = reverse(
            "apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session_name}
        )
        assertContains(response, prev_applicaitons_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        # Step check previous applications
        # ----------------------------------------------------------------------

        response = client.get(prev_applicaitons_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        fill_job_seeker_infos_url = reverse(
            "apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session_name}
        )
        assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)

        # Fill job seeker infos
        # ----------------------------------------------------------------------
        contract_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session_name})
        response = client.get(fill_job_seeker_infos_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session_name}
        )
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)

        NEW_POLE_EMPLOI_ID = "1234567A"
        post_data = {
            "pole_emploi_id": NEW_POLE_EMPLOI_ID,
            "ban_api_resolved_address": "10 rue des jardins 67118 Geispolsheim",
            "address_line_1": "10 rue des jardins",
            "post_code": geispolsheim.post_codes[0],
            "insee_code": geispolsheim.code_insee,
            "city": geispolsheim.name,
            "fill_mode": "ban_api",
        }
        response = client.post(fill_job_seeker_infos_url, data=post_data)
        assertRedirects(response, contract_url)
        assert client.session[hire_session_name]["job_seeker_info_forms_data"] == {
            "personal_data": {
                "pole_emploi_id": NEW_POLE_EMPLOI_ID,
                "lack_of_pole_emploi_id_reason": "",
            },
            "user_address": {
                "ban_api_resolved_address": "10 rue des jardins 67118 Geispolsheim",
                "address_line_1": "10 rue des jardins",
                "address_line_2": "",
                "post_code": geispolsheim.post_codes[0],
                "insee_code": geispolsheim.code_insee,
                "city": geispolsheim.name,
                "fill_mode": "ban_api",
                "address_for_autocomplete": None,
            },
        }
        # Check that no assignment was created
        # ----------------------------------------------------------------------
        assert not JobSeekerAssignment.objects.exists()

        # Contract infos
        # ----------------------------------------------------------------------
        response = client.get(contract_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        assertContains(response, NEXT_BUTTON_MARKUP, html=True)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)
        assertContains(
            response, reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session_name})
        )  # Back button URL

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
            "nb_hours_per_week": 4,
            "planned_training_hours": 5,
            "contract_type": ContractType.APPRENTICESHIP,
            "qualification_type": QualificationType.STATE_DIPLOMA,
            "qualification_level": QualificationLevel.LEVEL_4,
            "hired_job": company.job_description_through.first().pk,
        }
        response = client.post(contract_url, data=post_data)
        geiq_eligibility_url = reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": hire_session_name})
        assertRedirects(response, geiq_eligibility_url, fetch_redirect_response=False)

        # Step GEIQ eligibility
        # ----------------------------------------------------------------------
        geiq_criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire", kwargs={"session_uuid": hire_session_name}
        )

        response = client.get(geiq_eligibility_url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")

        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session_name})
        response = client.post(
            geiq_eligibility_url,
            data={"choice": "True"},
            headers={"hx-request": "true"},
        )
        assertRedirects(
            response,
            add_url_params(geiq_criteria_url, {"back_url": check_infos_url, "next_url": confirmation_url}),
            fetch_redirect_response=False,
        )
        htmx_response = client.get(geiq_criteria_url, headers={"hx-request": "true"})
        assert htmx_response.status_code == 200

        response = client.post(
            add_url_params(geiq_criteria_url, {"back_url": check_infos_url, "next_url": confirmation_url}),
            data={
                "jeune_26_ans": "on",
                "jeune_de_moins_de_26_ans_sans_qualification": "on",
                "proof_of_eligibility": "on",
            },
        )
        assertRedirects(response, confirmation_url, fetch_redirect_response=False)

        diag = GEIQEligibilityDiagnosis.objects.get(job_seeker=job_seeker)
        assert diag.expires_at == timezone.localdate() + relativedelta(months=6)

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assert JobSeekerAssignment.objects.filter(
            job_seeker=job_seeker,
            professional=user,
            prescriber_organization=None,
            company=company,
            last_action_kind=ActionKind.GEIQ_ELIGIBILITY,
        ).exists()

        # Confirmation
        # ----------------------------------------------------------------------
        response = client.get(confirmation_url)
        assertContains(response, CONFIRM_BUTTON_MARKUP % job_seeker.get_inverted_full_name(), html=True)
        assertContains(response, contract_url)  # Back button URL
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))
        response = client.post(confirmation_url)

        job_application = JobApplication.objects.select_related("job_seeker__jobseeker_profile").get(
            sender=user, to_company=company
        )
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url, fetch_redirect_response=False)

        assert job_application.job_seeker == job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None
        assert job_application.qualification_type == QualificationType.STATE_DIPLOMA
        assert job_application.qualification_level == QualificationLevel.LEVEL_4

        assert job_application.job_seeker.jobseeker_profile.pole_emploi_id == NEW_POLE_EMPLOI_ID
        assert job_application.job_seeker.address_line_1 == "10 rue des jardins"

        # Get application detail
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assert JobSeekerAssignment.objects.filter(
            job_seeker=job_seeker,
            professional=user,
            company=company,
            last_action_kind=ActionKind.HIRE,
        ).exists()


class TestUpdateJobSeekerForHire(UpdateJobSeekerTestMixin):
    FINAL_REDIRECT_VIEW_NAME = "job_seekers_views:check_job_seeker_info_for_hire"

    def test_as_job_seeker(self, client):
        self._check_nothing_permitted(client, self.job_seeker)

    def test_as_unauthorized_prescriber(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self._check_nothing_permitted(client, prescriber)

    def test_as_unauthorized_prescriber_that_created_proxied_job_seeker(self, client, snapshot):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            prescriber,
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )

    def test_as_unauthorized_prescriber_that_created_the_non_proxied_job_seeker(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self.job_seeker.created_by = prescriber
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_nothing_permitted(client, prescriber)

    def test_as_authorized_prescriber_with_proxied_job_seeker(self, client, snapshot):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = PrescriberFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            authorized_prescriber,
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )

    def test_as_authorized_prescriber_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        self._check_only_administrative_allowed(client, authorized_prescriber)

    def test_as_company_with_proxied_job_seeker(self, client, snapshot):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            self.company.members.first(),
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )

    def test_as_company_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(client, self.company.members.first())

    def test_as_company_with_non_proxied_job_seeker_with_place_infos(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])

        # Set birth place infos
        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate
        geispolsheim_commune = Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate)
        self.job_seeker.jobseeker_profile.birth_place = geispolsheim_commune
        self.job_seeker.jobseeker_profile.birth_country_id = Country.FRANCE_ID
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_place", "birth_country"])
        self._check_only_administrative_allowed(client, self.company.members.first())

        # Check that birth place infos are still there
        assert self.job_seeker.jobseeker_profile.birth_place == geispolsheim_commune
        assert self.job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID

    def test_with_invalid_job_seeker_session(self, client):
        client.force_login(self.company.members.first())
        invalid_session_name = uuid.uuid4()
        kwargs = {"session_uuid": invalid_session_name}
        for url in [
            reverse("job_seekers_views:update_job_seeker_step_1", kwargs=kwargs),
            reverse("job_seekers_views:update_job_seeker_step_2", kwargs=kwargs),
            reverse("job_seekers_views:update_job_seeker_step_3", kwargs=kwargs),
            reverse("job_seekers_views:update_job_seeker_step_end", kwargs=kwargs),
        ]:
            response = client.get(url)
            assert response.status_code == 404

    def test_with_job_seeker_without_nir(self, client, snapshot):
        # Make sure the job seeker does not manage its own account (and has no nir)
        self.job_seeker.jobseeker_profile.nir = ""
        self.job_seeker.jobseeker_profile.lack_of_nir_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])

        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            self.company.members.first(),
            extra_post_data_1={
                "nir": "",
                "lack_of_nir": True,
                "lack_of_nir_reason": LackOfNIRReason.NO_NIR.value,
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )
        # Check that we could update its NIR infos
        assert self.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NO_NIR

    def test_as_company_that_last_step_doesnt_crash_with_direct_access(self, client):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_that_last_step_doesnt_crash_with_direct_access(client, self.company.members.first())


class TestFindJobSeekerForHireView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(with_membership=True)

    def get_check_nir_url(self, client):
        # Init session
        start_url = reverse("apply:start_hire", kwargs={"company_pk": self.company.pk})
        client.get(start_url, follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        return reverse("job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name})

    def test_job_seeker_found_with_nir(self, client):
        user = self.company.members.first()
        client.force_login(user)

        job_seeker = JobSeekerFactory(first_name="Sylvie", last_name="Martin")

        check_nir_url = self.get_check_nir_url(client)
        response = client.get(check_nir_url)
        assertContains(response, "Déclarer une embauche")

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "preview": 1})
        assertContains(response, "MARTIN Sylvie")
        # Confirmation modal is shown
        assert response.context["preview_mode"] is True

        hire_session_name = get_session_name(client.session, HIRE_SESSION_KIND)
        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": 1})
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info_for_hire",
                kwargs={"session_uuid": hire_session_name},
                query={"job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_job_seeker_found_with_email(self, client):
        user = self.company.members.first()
        client.force_login(user)

        job_seeker = JobSeekerFactory(first_name="Sylvie", last_name="Martin")
        INVALID_NIR = "123456"

        check_nir_url = self.get_check_nir_url(client)
        response = client.get(check_nir_url)
        assertContains(response, "Déclarer une embauche")

        response = client.post(check_nir_url, data={"nir": INVALID_NIR, "preview": 1})
        assertContains(response, "Le numéro de sécurité sociale est trop court")
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        search_by_email_url = reverse(
            "job_seekers_views:search_by_email_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertContains(
            response,
            f"""
            <a href="{search_by_email_url}"
                class="btn btn-link p-0"
                data-matomo-event="true"
                data-matomo-category="nir-temporaire"
                data-matomo-action="etape-suivante"
                data-matomo-option="candidature">
               Cliquez ici pour accéder à l'étape suivante.
            </a>
            """,
            html=True,
        )

        response = client.get(search_by_email_url)
        assertContains(response, "Déclarer une embauche")  # Check page title
        assertContains(response, check_nir_url)  # Check back button URL
        assertNotContains(response, INVALID_NIR)

        response = client.post(search_by_email_url, data={"email": job_seeker.email, "preview": 1})
        assertContains(response, "MARTIN Sylvie")
        # Confirmation modal is shown
        assert response.context["preview_mode"] is True

        hire_session_name = get_session_name(client.session, HIRE_SESSION_KIND)
        response = client.post(search_by_email_url, data={"email": job_seeker.email, "confirm": 1})
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info_for_hire",
                kwargs={"session_uuid": hire_session_name},
                query={"job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_no_job_seeker_redirect_to_create(self, client):
        user = self.company.members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            with_address=True,
            jobseeker_profile__with_hexa_address=True,
        )

        check_nir_url = self.get_check_nir_url(client)
        response = client.get(check_nir_url)
        assertContains(response, "Déclarer une embauche")

        response = client.post(check_nir_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": 1})

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        search_by_email_url = reverse(
            "job_seekers_views:search_by_email_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, search_by_email_url)

        response = client.get(search_by_email_url)
        assertContains(response, "Déclarer une embauche")  # Check page title
        assertContains(response, check_nir_url)  # Check back button URL
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)

        response = client.post(search_by_email_url, data={"email": dummy_job_seeker.email})
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:create_job_seeker_step_1_for_hire",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )

        hire_session_name = get_session_name(client.session, HIRE_SESSION_KIND)
        expected_job_seeker_session = {
            "config": {
                "tunnel": "hire",
                "from_url": reverse("dashboard:index"),  # Hire: reset_url = dashboard
            },
            "apply": {
                "company_pk": self.company.pk,
                "session_uuid": hire_session_name,
            },
            "user": {
                "email": dummy_job_seeker.email,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session


class TestCheckJobSeekerInformationsForHire:
    @pytest.mark.parametrize(
        "job_seeker_kwargs",
        [
            pytest.param(
                {
                    "title": "",
                    "first_name": "",
                    "last_name": "",
                    "email": None,
                    "phone": "",
                    "jobseeker_profile__birthdate": None,
                    "jobseeker_profile__nir": "",
                    "jobseeker_profile__lack_of_nir_reason": LackOfNIRReason.NO_NIR,
                    "jobseeker_profile__lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
                    "jobseeker_profile__education_level": "",
                },
                id="job_seeker_with_few_datas",
            ),
            pytest.param(
                {
                    "for_snapshot": True,
                    "born_in_france": True,
                    "jobseeker_profile__with_pole_emploi_id": True,
                    "jobseeker_profile__pole_emploi_id": "09443041",
                    "jobseeker_profile__resourceless": True,
                    "jobseeker_profile__rqth_employee": True,
                    "jobseeker_profile__oeth_employee": True,
                    "jobseeker_profile__unemployed_since": AllocationDuration.FROM_12_TO_23_MONTHS,
                    "jobseeker_profile__has_rsa_allocation": RSAAllocation.YES_WITH_MARKUP,
                    "jobseeker_profile__rsa_allocation_since": AllocationDuration.MORE_THAN_24_MONTHS,
                    "jobseeker_profile__ass_allocation_since": AllocationDuration.FROM_6_TO_11_MONTHS,
                    "jobseeker_profile__aah_allocation_since": AllocationDuration.LESS_THAN_6_MONTHS,
                    "jobseeker_profile__ase_exit": True,
                    "jobseeker_profile__isolated_parent": True,
                    "jobseeker_profile__housing_issue": True,
                    "jobseeker_profile__refugee": True,
                    "jobseeker_profile__detention_exit_or_ppsmj": True,
                    "jobseeker_profile__low_level_in_french": True,
                    "jobseeker_profile__mobility_issue": True,
                },
                id="job_seeker_with_all_datas",
            ),
            pytest.param(
                {
                    "for_snapshot": True,
                    "born_in_france": True,
                    "jobseeker_profile__with_pole_emploi_id": True,
                    "jobseeker_profile__pole_emploi_id": "09443041",
                    "jobseeker_profile__resourceless": True,
                },
                id="job_seeker_with_single_other_data",
            ),
            pytest.param(
                {"for_snapshot": True, "jobseeker_profile__birth_country_id": 126},
                id="job_seeker_not_born_in_france",
            ),
        ],
    )
    def test_company(self, client, job_seeker_kwargs, snapshot):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        job_seeker_kwargs["jobseeker_profile__birth_place"] = (
            Commune.objects.by_insee_code_and_period("59183", datetime.date(1990, 1, 1))
            if job_seeker_kwargs.get("born_in_france")
            else None
        )
        job_seeker = JobSeekerFactory(
            last_checked_at=timezone.make_aware(datetime.datetime(2023, 10, 1, 12, 0, 0)), **job_seeker_kwargs
        )
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, job_seeker, {})
        url_check_infos = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}
        )
        response = client.get(url_check_infos)
        content = parse_response_to_soup(
            response,
            selector=".personal-infos",
            replace_in_attr=[
                ("href", str(job_seeker.public_id), "JOB_SEEKER_PUBLIC_ID"),
                ("href", hire_session.name, "HIRE_SESSION_NAME"),
            ],
        )
        assert pretty_indented(content) == snapshot(name="personal-infos")
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        params = {
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": url_check_infos,
        }
        assertContains(
            response,
            (
                f'<a href="{reverse("job_seekers_views:update_job_seeker_start", query=params)}"\n'
                '                   class="btn btn-ico btn-outline-primary"\n'
                '                   aria-label="Modifier les informations personnelles de '
                f'{job_seeker.get_inverted_full_name()}">\n'
                '                    <i class="ri-pencil-line fw-medium" aria-hidden="true"></i>\n'
                "                    <span>Modifier</span>\n                </a>"
            ),
            html=True,
        )
        assertContains(
            response,
            reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}),
        )
        assertContains(
            response,
            reverse("apply:start_hire", kwargs={"company_pk": company.pk}),
        )
        assertContains(response, reverse("dashboard:index"))

    def test_geiq(self, client, snapshot):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        job_seeker = JobSeekerFactory(
            for_snapshot=True,
            jobseeker_profile__nir="",
            jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.NO_NIR,
            last_checked_at=timezone.make_aware(datetime.datetime(2023, 10, 1, 12, 0, 0)),
        )
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, job_seeker, {})
        url_check_infos = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}
        )
        response = client.get(url_check_infos)
        content = parse_response_to_soup(
            response,
            selector=".personal-infos",
            replace_in_attr=[
                ("href", str(job_seeker.public_id), "JOB_SEEKER_PUBLIC_ID"),
                ("href", hire_session.name, "HIRE_SESSION_NAME"),
            ],
        )
        assert pretty_indented(content) == snapshot(name="personal-infos")
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        params = {
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": url_check_infos,
        }
        assertContains(
            response,
            f'<a href="{escape(reverse("job_seekers_views:update_job_seeker_start", query=params))}"',
        )
        assertContains(
            response,
            reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}),
        )
        assertContains(
            response,
            reverse("apply:start_hire", kwargs={"company_pk": company.pk}),
        )
        assertContains(response, reverse("dashboard:index"))


class TestCheckPreviousApplicationsForHireView:
    @pytest.fixture(autouse=True)
    def self(cls):
        cls.job_seeker = JobSeekerFactory()

    def test_iae_employer(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {})

        url = reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name})
        next_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name})
        response = client.get(url)
        assertRedirects(response, next_url)

        # with previous job application
        JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker=self.job_seeker, to_company=company)
        response = client.get(url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        assertContains(response, "Ce candidat a déjà postulé pour cette entreprise")
        response = client.post(
            reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}),
            data={"force_new_application": "force"},
        )
        assertRedirects(response, next_url)

    def test_geiq_employer(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {})

        url = reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name})
        next_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name})
        response = client.get(url)
        assertRedirects(response, next_url)

        # with previous job application
        JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker=self.job_seeker, to_company=company)
        response = client.get(url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        assertContains(response, "Ce candidat a déjà postulé pour cette entreprise")
        response = client.post(
            reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}),
            data={"force_new_application": "force"},
        )
        assertRedirects(response, next_url)

    def test_other_employer(self, client):
        # not IAE or GEIQ
        company = CompanyFactory(kind=CompanyKind.EA, with_membership=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {})

        url = reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name})
        next_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name})
        response = client.get(url)
        assertRedirects(response, next_url)

        # with previous job application
        JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker=self.job_seeker, to_company=company)
        response = client.get(url)
        assertTemplateNotUsed(response, "utils/templatetags/approval_box.html")
        assertContains(response, "Ce candidat a déjà postulé pour cette entreprise")
        response = client.post(
            reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}),
            data={"force_new_application": "force"},
        )
        assertRedirects(response, next_url)

    @freeze_time("2026-04-09")
    def test_num_queries(self, client, snapshot):
        now = timezone.now()
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        job_seeker = JobSeekerFactory()
        employer = company.members.first()
        client.force_login(employer)
        hire_session = fake_session_initialization(client, company, job_seeker, {})
        JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_job_seeker=True,
            created_at=now - relativedelta(months=6),
        )
        JobApplicationFactory(
            job_seeker=job_seeker, to_company=company, sent_by_employer=True, created_at=now - relativedelta(months=3)
        )
        JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_prescriber=True,
            sender_prescriber_organization__for_snapshot=True,
            created_at=now - relativedelta(hours=12),
        )

        url = reverse("apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name})

        with assertSnapshotQueries(snapshot(name="get_with_previous_application")):
            client.get(url)

    @freeze_time("2026-03-25")
    def test_check_prev_applications_hire(self, client):
        DATE_FORMAT = "d F Y à H\\hi"
        company = CompanyFactory(with_jobs=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        user = company.members.first()
        client.force_login(user)
        now = timezone.now()
        old_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_job_seeker=True,
            created_at=now - relativedelta(months=13),
            state=JobApplicationState.PROCESSING,
        )
        application_in_period_refused = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_job_seeker=True,
            created_at=now - relativedelta(months=6),
            state=JobApplicationState.REFUSED,
        )
        application_in_period_accepted = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_job_seeker=True,
            created_at=now - relativedelta(months=3),
            state=JobApplicationState.ACCEPTED,
        )
        application_in_period_processing = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_job_seeker=True,
            created_at=now - relativedelta(months=1),
            state=JobApplicationState.PROCESSING,
        )

        hire_session = fake_session_initialization(client, company, job_seeker, {})
        prev_applicaitons_url = reverse(
            "apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}
        )
        response = client.get(prev_applicaitons_url)

        assertContains(response, "Ce candidat a déjà postulé pour cette entreprise")

        assertContains(response, date_format(localtime(application_in_period_refused.created_at), DATE_FORMAT))
        assertContains(response, date_format(localtime(application_in_period_processing.created_at), DATE_FORMAT))
        assertNotContains(response, date_format(localtime(old_application.created_at), DATE_FORMAT))
        assertNotContains(response, date_format(localtime(application_in_period_accepted.created_at), DATE_FORMAT))

    @freeze_time("2026-03-27")
    def test_display_prev_applications_according_to_sender_type_snapshot(self, client, snapshot):
        now = timezone.now()
        company = CompanyFactory(with_jobs=True, with_membership=True, for_snapshot=True)
        job_seeker = JobSeekerFactory(for_snapshot=True)
        employer = company.members.first()
        client.force_login(employer)

        application_by_job_seeker = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_job_seeker=True,
            created_at=now - relativedelta(months=6),
        )
        application_by_employer = JobApplicationFactory(
            job_seeker=job_seeker, to_company=company, sent_by_employer=True, created_at=now - relativedelta(months=3)
        )
        application_by_prescriber = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_prescriber=True,
            sender_prescriber_organization__for_snapshot=True,
            created_at=now - relativedelta(months=2),
        )

        hire_session = fake_session_initialization(client, company, job_seeker, {})
        prev_applications_url = reverse(
            "apply:check_prev_applications_for_hire", kwargs={"session_uuid": hire_session.name}
        )
        response = client.get(prev_applications_url)

        content = parse_response_to_soup(
            response,
            selector=".list-group.list-group-flush",
            replace_in_attr=[
                ("href", str(application_by_job_seeker.pk), "[PK of JobSeeker JobApplication]"),
                ("href", str(application_by_employer.pk), "[PK of Employer JobApplication]"),
                ("href", str(application_by_prescriber.pk), "[PK of Prescriber JobApplication]"),
            ],
        )
        assert pretty_indented(content) == snapshot


class TestEligibilityForHire:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_seeker = JobSeekerFactory(
            first_name="Ellie",
            last_name="Gibilitay",
            # Avoid redirect to fill user infos
            jobseeker_profile__with_pole_emploi_id=True,
            with_address=True,
            born_in_france=True,
        )

    def test_not_subject_to_eligibility(self, client):
        company = CompanyFactory(kind=CompanyKind.EA, with_membership=True)  # We don't want a GEIQ here
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {"selected_jobs": [], "contract_form_data": {"hiring_start_at": timezone.localdate()}},
        )
        response = client.get(reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assert response.status_code == 404

    def test_job_seeker_with_valid_diagnosis(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})
        response = client.get(reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(
            response,
            reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}),
            fetch_redirect_response=False,
        )

    def test_job_seeker_without_valid_diagnosis(self, client):
        PREFILLED_TEMPLATE = "eligibility/includes/iae/criteria_filled_from_job_seeker.html"
        # Profile last checked a long time ago to prevent pre-filled criteria
        self.job_seeker.last_checked_at = timezone.now() - datetime.timedelta(days=10)
        self.job_seeker.save(update_fields=["last_checked_at"])
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        assert not self.job_seeker.has_valid_diagnosis(for_siae=company)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {"selected_jobs": [], "contract_form_data": {"hiring_start_at": timezone.localdate()}},
        )
        response = client.get(reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Valider l'éligibilité IAE")
        assertContains(
            response,
            reverse("job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}),
        )  # cancel button
        assertTemplateNotUsed(response, PREFILLED_TEMPLATE)

        # Update profile to now have some pre-filled criteria
        self.job_seeker.jobseeker_profile.ase_exit = True
        self.job_seeker.jobseeker_profile.housing_issue = True
        self.job_seeker.jobseeker_profile.save(update_fields=["ase_exit", "housing_issue"])
        self.job_seeker.last_checked_at = timezone.now()
        self.job_seeker.save(update_fields=["last_checked_at"])
        response = client.get(reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Valider l'éligibilité IAE")
        assertContains(
            response,
            reverse("job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}),
        )  # cancel button
        assertTemplateUsed(response, PREFILLED_TEMPLATE)
        prefilled_criteria = [c.kind for c in response.context["form"].initial["administrative_criteria"]]
        assert AdministrativeCriteriaKind.ASE in prefilled_criteria
        assert AdministrativeCriteriaKind.PSH_PR in prefilled_criteria
        assert response.context["form"].initial["level_2_8"] is True  # ASE criterion
        assert response.context["form"].initial["level_2_12"] is True  # PSH_PR / housing_issue criterion

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)
        response = client.post(
            reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}),
            data={
                # Administrative criteria level 1.
                f"{criterion1.key}": "on",
                # Administrative criteria level 2.
                f"{criterion2.key}": "on",
                f"{criterion3.key}": "on",
            },
        )
        assertRedirects(
            response,
            reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}),
            fetch_redirect_response=False,
        )
        assert self.job_seeker.has_valid_diagnosis(for_siae=company)

    def test_without_contract_infos(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {})
        response = client.get(reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(
            response,
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}),
            fetch_redirect_response=False,
        )


class TestGEIQEligibilityForHire:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_seeker = JobSeekerFactory(
            first_name="Ellie",
            last_name="Gibilitay",
            # Avoid redirect to fill user infos
            jobseeker_profile__with_pole_emploi_id=True,
            with_address=True,
            born_in_france=True,
        )

    def test_not_geiq(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {"selected_jobs": [], "contract_form_data": {"hiring_start_at": timezone.localdate()}},
        )
        response = client.get(reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assert response.status_code == 404

    def test_job_seeker_with_valid_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_employer=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        company = diagnosis.author_geiq
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})
        response = client.get(reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(
            response,
            reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}),
            fetch_redirect_response=False,
        )

    def test_job_seeker_without_valid_diagnosis(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        assert not GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, company).exists()
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "contract_form_data": {
                    "hiring_start_at": timezone.localdate(),
                    "hired_job": company.job_description_through.first().pk,
                    "nb_hours_per_week": 4,
                    "planned_training_hours": 5,
                    "contract_type": ContractType.APPRENTICESHIP.value,
                    "qualification_type": QualificationType.STATE_DIPLOMA.value,
                    "qualification_level": QualificationLevel.LEVEL_4.value,
                },
            },
        )
        response = client.get(reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Eligibilité GEIQ")
        assertContains(
            response,
            reverse("job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}),
        )  # cancel button

        response = client.post(
            reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}),
            data={"choice": "True"},
            headers={"hx-request": "true"},
        )
        criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire",
            kwargs={"session_uuid": hire_session.name},
            query={
                "back_url": reverse(
                    "job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}
                ),
                "next_url": reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}),
            },
        )
        assertRedirects(
            response,
            criteria_url,
            fetch_redirect_response=False,
        )
        htmx_response = client.get(criteria_url, headers={"hx-request": "true"})
        assert htmx_response.status_code == 200

        response = client.post(
            criteria_url,
            data={
                "jeune_26_ans": "on",
                "jeune_de_moins_de_26_ans_sans_qualification": "on",
                "proof_of_eligibility": "on",
            },
        )
        assertRedirects(
            response,
            reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}),
            fetch_redirect_response=False,
        )
        assert GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, company).exists()

    def test_without_contract_infos(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {})
        response = client.get(reverse("apply:geiq_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(
            response,
            reverse("job_seekers_views:check_job_seeker_info_for_hire", kwargs={"session_uuid": hire_session.name}),
            fetch_redirect_response=False,
        )


class TestFillJobSeekerInfosForHire:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()
        self.company = CompanyFactory(with_membership=True)
        if self.company.is_subject_to_iae_rules:
            IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        elif self.company.kind == CompanyKind.GEIQ:
            GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)

        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def accept_contract(self, client, session_uuid):
        accept_contract_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": session_uuid})
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": session_uuid})
        post_data = {
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
            "confirmed": True,
        }
        if self.company.kind == CompanyKind.GEIQ:
            create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)  # For hired_job field
            post_data.update(
                {
                    "contract_type": ContractType.APPRENTICESHIP,
                    "nb_hours_per_week": 10,
                    "qualification_type": QualificationType.CQP,
                    "qualification_level": QualificationLevel.LEVEL_4,
                    "planned_training_hours": 20,
                    "hired_job": JobDescriptionFactory(company=self.company).pk,
                }
            )
        response = client.post(accept_contract_url, data=post_data)
        assertRedirects(response, confirmation_url, fetch_redirect_response=False)
        response = client.post(confirmation_url)
        job_application = JobApplication.objects.select_related("job_seeker__jobseeker_profile").get(
            sender=self.company.members.first(), to_company=self.company
        )
        if self.company.is_subject_to_iae_rules:
            expected_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        else:
            expected_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, expected_url, fetch_redirect_response=False)
        return job_application

    def test_no_missing_data_iae(self, client, snapshot):
        # Ensure company is SIAE kind since it will trigger an extra query for eligibility diagnosis
        # changing the SQL queries snapshot
        if not self.company.is_subject_to_iae_rules:
            self.company.kind = random.choice(list(CompanyKind.siae_kinds()))
            self.company.convention = SiaeConventionFactory(kind=self.company.kind)
            self.company.save(update_fields=["convention", "kind", "updated_at"])
            IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(self.company.members.first())
        hire_session = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []})

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(
                reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name})
            )
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))

    @pytest.mark.parametrize("birth_country", [None, "france", "other"])
    def test_no_birthdate(self, client, birth_country):
        self.job_seeker.jobseeker_profile.birthdate = None
        if birth_country == "france":
            self.job_seeker.jobseeker_profile.birth_country_id = Country.FRANCE_ID
            self.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
                "59183", datetime.date(1990, 1, 1)
            )
        elif birth_country == "other":
            self.job_seeker.jobseeker_profile.birth_country = (
                Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
            )
            self.job_seeker.jobseeker_profile.birth_place = None
        else:
            self.job_seeker.jobseeker_profile.birth_country = None
            self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])

        client.force_login(self.company.members.first())
        session_uuid = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []}).name
        fill_job_seeker_infos_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid})
        accept_contract_infos_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": session_uuid})

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        if self.company.is_subject_to_iae_rules:
            assertContains(response, "Éligible à l’IAE")

        COUNTRY_FIELD_ID = 'id="id_birth_country"'
        PLACE_FIELD_ID = 'id="id_birth_place"'
        NEW_BIRTHDATE = datetime.date(1990, 1, 1)
        if birth_country == "other":
            assertNotContains(response, COUNTRY_FIELD_ID)
            assertNotContains(response, PLACE_FIELD_ID)
            invalid_post_data = {"birthdate": ""}

            def assertForm(form):
                assertFormError(form, "birthdate", "Ce champ est obligatoire.")

            valid_post_data = {"birthdate": NEW_BIRTHDATE}
            birth_place = None
        else:
            assertContains(response, COUNTRY_FIELD_ID)
            assertContains(response, PLACE_FIELD_ID)
            birth_place = (
                Commune.objects.filter(
                    # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                    Q(start_date__gt=datetime.date(1900, 1, 1)),
                    # Must be a valid choice for the user current birthdate.
                    Q(start_date__lte=NEW_BIRTHDATE),
                    Q(end_date__gte=NEW_BIRTHDATE) | Q(end_date=None),
                )
                .order_by("?")
                .first()
            )

            bad_birthdate = birth_place.start_date - datetime.timedelta(days=1)
            invalid_post_data = {
                "birthdate": bad_birthdate,
                "birth_place": birth_place.pk,
                "birth_country": Country.FRANCE_ID,
            }

            def assertForm(form):
                assertFormError(
                    form,
                    "birth_place",
                    (
                        f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date "
                        f"du {bad_birthdate:%d/%m/%Y}"
                    ),
                )

            valid_post_data = {
                "birthdate": NEW_BIRTHDATE,
                "birth_place": birth_place.pk,
                "birth_country": Country.FRANCE_ID,
            }

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=invalid_post_data)
        assert response.status_code == 200
        assertForm(response.context["form_birth_data"])
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=valid_post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "birth_data": valid_post_data,
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, NEW_BIRTHDATE)

        # Check that birth infos are saved (if modified) after filling contract info step
        self.accept_contract(client, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.birthdate == NEW_BIRTHDATE
        assert self.job_seeker.jobseeker_profile.birth_place == birth_place
        if birth_country != "other":
            assert self.job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID

    @pytest.mark.parametrize("in_france", [True, False])
    def test_no_birth_country(self, client, in_france):
        assert self.job_seeker.jobseeker_profile.birthdate
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_country", "birth_place"])

        client.force_login(self.company.members.first())
        session_uuid = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []}).name
        fill_job_seeker_infos_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid})
        accept_contract_infos_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": session_uuid})

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        if self.company.is_subject_to_iae_rules:
            assertContains(response, "Éligible à l’IAE")

        if in_france:
            new_country = Country.objects.get(pk=Country.FRANCE_ID)
            new_place = (
                Commune.objects.filter(
                    # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                    Q(start_date__gt=datetime.date(1900, 1, 1)),
                    # Must be a valid choice for the user current birthdate.
                    Q(start_date__lte=self.job_seeker.jobseeker_profile.birthdate),
                    Q(end_date__gte=self.job_seeker.jobseeker_profile.birthdate) | Q(end_date=None),
                )
                .order_by("?")
                .first()
            )

            invalid_post_data = {
                "birth_place": "",
                "birth_country": Country.FRANCE_ID,
            }

            def assertForm(form):
                assertFormError(
                    form,
                    None,
                    (
                        "La commune de naissance doit être spécifiée si et seulement si le pays de naissance est "
                        "la France."
                    ),
                )

            valid_post_data = {
                "birth_place": new_place.pk,
            }
        else:
            new_country = Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
            new_place = None

            invalid_post_data = {"birth_country": ""}

            def assertForm(form):
                assertFormError(form, "birth_country", "Le pays de naissance est obligatoire.")

            valid_post_data = {"birth_country": new_country.pk}

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=invalid_post_data)
        assert response.status_code == 200
        assertForm(response.context["form_birth_data"])
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=valid_post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "birth_data": {
                "birth_place": new_place and new_place.pk,
                "birth_country": new_country.pk,
            }
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f'<option value="{new_country.pk}" selected>')

        # Check that birth infos are saved (if modified) after filling contract info step
        self.accept_contract(client, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.birth_country_id == new_country.pk
        assert self.job_seeker.jobseeker_profile.birth_place == new_place

    @pytest.mark.parametrize("address", ["empty", "incomplete"])
    def test_no_address(self, client, address):
        address_kwargs = {
            "address_line_1": "",
            "city": "",
            "post_code": "",
        }
        if address == "incomplete":
            address_kwargs.pop(random.choice(list(address_kwargs.keys())))

        # Remove job seeker address
        for key, value in address_kwargs.items():
            setattr(self.job_seeker, key, value)
        self.job_seeker.save(update_fields=address_kwargs.keys())

        client.force_login(self.company.members.first())
        hire_session = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        if self.company.is_subject_to_iae_rules:
            assertContains(response, "Éligible à l’IAE")

        post_data = {
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "birth_place": self.job_seeker.jobseeker_profile.birth_place.pk,
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "address_line_1": "128 Rue de Grenelle",
            "address_line_2": "",
            "post_code": "67118",
            "city": "Geispolsheim",
            "fill_mode": "ban_api",
            "insee_code": "67152",
            "ban_api_resolved_address": "128 Rue de Grenelle 67118 Geispolsheim",
            "address_for_autocomplete": "67152_1234_00128",
        }
        # Test with invalid data
        response = client.post(
            reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name}),
            data=post_data | {"address_line_1": "", "address_for_autocomplete": ""},
        )
        assert response.status_code == 200
        assertFormError(response.context["form_user_address"], "address_for_autocomplete", "Ce champ est obligatoire.")
        # Then with valid data
        response = client.post(
            reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name}), data=post_data
        )
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assert client.session[hire_session.name]["job_seeker_info_forms_data"] == {
            "user_address": {
                "address_line_1": "128 Rue de Grenelle",
                "address_line_2": "",
                "post_code": "67118",
                "city": "Geispolsheim",
                "fill_mode": "ban_api",
                "insee_code": "67152",
                "ban_api_resolved_address": "128 Rue de Grenelle 67118 Geispolsheim",
                "address_for_autocomplete": "67152_1234_00128",
            },
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, "128 Rue de Grenelle")

        # Check that address is saved on job seeker after contract signature
        job_application = self.accept_contract(client, hire_session.name)
        assert job_application.job_seeker.address_line_1 == "128 Rue de Grenelle"

    def test_no_nir(self, client):
        # Remove job seeker nir, with or without a reason
        self.job_seeker.jobseeker_profile.nir = ""
        self.job_seeker.jobseeker_profile.lack_of_nir_reason = random.choice(
            [LackOfNIRReason.NO_NIR, LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER, ""]
        )
        self.job_seeker.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])

        client.force_login(self.company.members.first())
        session_uuid = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []}).name
        fill_job_seeker_infos_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid})
        accept_contract_infos_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": session_uuid})

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        if self.company.is_subject_to_iae_rules:
            assertContains(response, "Éligible à l’IAE")

        NEW_NIR = "197013625838386"
        post_data = {
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "birth_place": self.job_seeker.jobseeker_profile.birth_place.pk,
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "nir": NEW_NIR,
        }
        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=post_data | {"nir": ""})
        assert response.status_code == 200
        assertFormError(
            response.context["form_personal_data"], "nir", "Le numéro de sécurité sociale n'est pas valide"
        )
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "personal_data": {
                "lack_of_nir": False,
                "lack_of_nir_reason": "",
                "nir": NEW_NIR,
            },
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, NEW_NIR)

        # Check that the NIR is saved on job seeker after contract signature
        job_application = self.accept_contract(client, session_uuid)
        assert job_application.job_seeker.jobseeker_profile.nir == NEW_NIR

    @pytest.mark.parametrize("with_lack_of_pole_emploi_id_reason", [True, False])
    def test_no_pole_emploi_id(self, client, with_lack_of_pole_emploi_id_reason):
        POLE_EMPLOI_FIELD_MARKER = 'id="id_pole_emploi_id"'
        client.force_login(self.company.members.first())
        # Remove job seeker nir, with or without a reason
        self.job_seeker.jobseeker_profile.pole_emploi_id = ""
        if with_lack_of_pole_emploi_id_reason:
            self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason = random.choice(
                [LackOfPoleEmploiId.REASON_NOT_REGISTERED, LackOfPoleEmploiId.REASON_FORGOTTEN]
            )
        else:
            self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["pole_emploi_id", "lack_of_pole_emploi_id_reason"])

        session_uuid = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []}).name
        fill_job_seeker_infos_url = reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid})
        accept_contract_infos_url = reverse("apply:hire_contract_infos", kwargs={"session_uuid": session_uuid})

        response = client.get(fill_job_seeker_infos_url)

        NEW_POLE_EMPLOI_ID = "1234567A"
        PERSONAL_DATA_SESSION_KEY = "job_seeker_info_forms_data"
        if with_lack_of_pole_emploi_id_reason:
            assertRedirects(response, accept_contract_infos_url)
            assert PERSONAL_DATA_SESSION_KEY not in client.session[session_uuid]
        else:
            assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
            assertContains(response, NEXT_BUTTON_MARKUP, html=True)
            # If no reason is present, the pole_emploi_id field is shown
            assertContains(response, POLE_EMPLOI_FIELD_MARKER)
            # Trying to skip to contract step must redirect back to job seeker info step if a reason is missing
            response = client.get(accept_contract_infos_url)
            assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)
            assertMessages(
                response,
                [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
            )
            # Test with invalid data
            response = client.post(
                fill_job_seeker_infos_url, data={"pole_emploi_id": "", "lack_of_pole_emploi_id_reason": ""}
            )
            assert response.status_code == 200
            assertFormError(
                response.context["form_personal_data"],
                None,
                "Renseignez soit un identifiant France Travail, soit la raison de son absence.",
            )
            response = client.post(
                fill_job_seeker_infos_url,
                data={"pole_emploi_id": NEW_POLE_EMPLOI_ID, "lack_of_pole_emploi_id_reason": ""},
            )
            assertRedirects(response, accept_contract_infos_url)
            assert client.session[session_uuid][PERSONAL_DATA_SESSION_KEY] == {
                "personal_data": {
                    "pole_emploi_id": NEW_POLE_EMPLOI_ID,
                    "lack_of_pole_emploi_id_reason": "",
                },
            }
            # If you come back to the view, it is pre-filled with session data
            response = client.get(fill_job_seeker_infos_url)
            assertContains(response, NEW_POLE_EMPLOI_ID)

        # Check that pole_emploi_id is saved (if modified) after filling contract info step
        self.accept_contract(client, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        if not with_lack_of_pole_emploi_id_reason:
            assert self.job_seeker.jobseeker_profile.pole_emploi_id == NEW_POLE_EMPLOI_ID
            assert self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason == ""
        else:
            assert self.job_seeker.jobseeker_profile.pole_emploi_id == ""
            assert self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason != ""

    def test_as_iae_company_eligibility_diagnosis_from_another_company(self, client):
        if self.company.is_subject_to_iae_rules:
            # Delete existing prescriber diagnosis
            self.job_seeker.eligibility_diagnoses.all().delete()
        else:
            # Ensure company is SIAE kind
            self.company.kind = random.choice(list(CompanyKind.siae_kinds()))
            self.company.convention = SiaeConventionFactory(kind=self.company.kind)
            self.company.save(update_fields=["convention", "kind", "updated_at"])
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True, job_seeker=self.job_seeker)
        ApprovalFactory(eligibility_diagnosis=eligibility_diagnosis, user=self.job_seeker)
        client.force_login(self.company.members.get())
        hire_session = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))

    def test_no_country_disable_with_certification(self, client):
        IdentityCertification.objects.create(
            jobseeker_profile=self.job_seeker.jobseeker_profile,
            certifier=IdentityCertificationAuthorities.API_PARTICULIER,
        )
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.pole_emploi_id = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_country", "birth_place", "pole_emploi_id"])

        client.force_login(self.company.members.first())
        hire_session = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []})

        birth_country = Country.objects.get(name="BORA-BORA")

        fill_job_seeker_infos_url = reverse(
            "apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name}
        )
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        if self.company.is_subject_to_iae_rules:
            assertContains(response, "Éligible à l’IAE")

        post_data = {
            "ban_api_resolved_address": self.job_seeker.geocoding_address,
            "address_line_1": self.job_seeker.address_line_1,
            "post_code": self.job_seeker.post_code,
            "city": self.job_seeker.city,
            "fill_mode": "ban_api",
            # Select the first and only one option
            "address_for_autocomplete": "0",
            "geocoding_score": 0.9714,
            "birthdate": self.job_seeker.jobseeker_profile.birthdate,
            # Provide country
            "birth_country": birth_country.pk,
            # Invalid data
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": "",
        }
        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=post_data)
        assert response.status_code == 200
        soup = parse_response_to_soup(response, selector="#id_birth_country")
        assert soup.attrs.get("disabled", False) is False
        [selected_option] = soup.find_all(attrs={"selected": True})
        assert selected_option.text == "BORA-BORA"


class TestHireContract:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()

        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def test_as_company(self, client, snapshot):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Éligible à l’IAE")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
        }
        response = client.post(
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}), data=post_data
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})
        assertRedirects(response, confirmation_url, fetch_redirect_response=False)
        response = client.get(confirmation_url)
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))

        # If you go back to contract infos, data is pre-filled
        response = client.get(reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f'value="{hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)}"')

        response = client.post(confirmation_url)
        job_application = JobApplication.objects.select_related("job_seeker").get(
            sender=company.members.first(), to_company=company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None

        assert hire_session.name not in client.session

    def test_cannot_hire_start_date_after_approval_expires(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})

        today = timezone.localdate()
        approval = ApprovalFactory(end_at=today + datetime.timedelta(days=1))
        self.job_seeker.approvals.add(approval)

        hiring_start_at = today + datetime.timedelta(days=2)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
        }
        response = client.post(
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}), data=post_data
        )
        assert response.status_code == 200
        assertFormError(
            response.context["form_accept"],
            "hiring_start_at",
            JobApplication.ERROR_HIRES_AFTER_APPROVAL_EXPIRES,
        )
        assert hire_session.name in client.session

    def test_as_company_eligibility_diagnosis_from_another_company(self, client):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True, job_seeker=self.job_seeker)
        ApprovalFactory(eligibility_diagnosis=eligibility_diagnosis, user=self.job_seeker)
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        client.force_login(company.members.get())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "PASS IAE valide")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
            "confirmed": "True",
        }
        response = client.post(
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}), data=post_data
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})
        assertRedirects(response, confirmation_url, fetch_redirect_response=False)
        response = client.get(confirmation_url)
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)

        job_application = JobApplication.objects.select_related("job_seeker").get(
            sender=company.members.first(), to_company=company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None

        assert hire_session.name not in client.session

    def test_as_geiq(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_employer=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        company = diagnosis.author_geiq
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Éligibilité GEIQ confirmée")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
            # GEIQ specific fields
            "hired_job": company.job_description_through.first().pk,
            "nb_hours_per_week": 4,
            "planned_training_hours": 5,
            "contract_type": ContractType.APPRENTICESHIP,
            "qualification_type": QualificationType.STATE_DIPLOMA,
            "qualification_level": QualificationLevel.LEVEL_4,
        }
        response = client.post(
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}), data=post_data
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})
        assertRedirects(response, confirmation_url)
        response = client.get(confirmation_url)
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)

        job_application = JobApplication.objects.get(sender=company.members.first(), to_company=company)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None

        assert hire_session.name not in client.session

    def test_redirect_fill_user_infos_when_needed(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_employer=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        company = diagnosis.author_geiq
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(client, company, self.job_seeker, {"selected_jobs": []})
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_place", "birth_country"])

        response = client.get(reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(
            response, reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name})
        )
        # It happens also with POST (but should not really happen)
        response = client.post(
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}),
            data={},
        )
        assertRedirects(
            response, reverse("apply:hire_fill_job_seeker_infos", kwargs={"session_uuid": hire_session.name})
        )

    def test_retrieval_of_session_data(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_place", "birth_country"])

        other_country = Country.objects.exclude(pk=Country.FRANCE_ID).first()
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "job_seeker_info_forms_data": {
                    "birth_data": {
                        "birth_place": None,
                        "birth_country": other_country.pk,
                    },
                },
            },
        )

        response = client.get(reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Éligible à l’IAE")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
        }
        response = client.post(
            reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}), data=post_data
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})
        assertRedirects(response, confirmation_url, fetch_redirect_response=False)
        response = client.get(confirmation_url)
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)

        job_application = JobApplication.objects.select_related("job_seeker__jobseeker_profile").get(
            sender=company.members.first(), to_company=company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None

        assert job_application.job_seeker.jobseeker_profile.birth_place_id is None
        assert job_application.job_seeker.jobseeker_profile.birth_country_id == other_country.pk

        assert hire_session.name not in client.session


class TestHireConfirmation:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            jobseeker_profile__with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def test_as_iae(self, client, snapshot):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        hiring_start_at = timezone.localdate()
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "contract_form_data": {"hiring_start_at": hiring_start_at},
            },
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(confirmation_url)
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, "Éligible à l’IAE")
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))
        assertContains(
            response,
            """\
            <li>
                <small>Poste retenu</small>
                    <i class="text-disabled">Non renseigné</i>
            </li>""",
            html=True,
        )

        response = client.post(confirmation_url)
        job_application = JobApplication.objects.select_related("job_seeker").get(
            sender=company.members.first(), to_company=company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.answer == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None
        assert job_application.hiring_start_at == hiring_start_at

        assert hire_session.name not in client.session

    def test_as_iae_missing_data(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(company.members.first())
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "contract_form_data": {"hiring_start_at": None},
            },
        )

        response = client.get(reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))

        response = client.post(reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assert not JobApplication.objects.exists()

    def test_as_iae_missing_eligibility(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        client.force_login(company.members.first())
        hiring_start_at = timezone.localdate()
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "contract_form_data": {"hiring_start_at": hiring_start_at},
            },
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})

        response = client.get(confirmation_url)
        assertRedirects(
            response,
            reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}),
        )
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Un diagnostic d'éligibilité est nécessaire pour déclarer cette embauche.",
                )
            ],
        )

        response = client.post(confirmation_url)
        assertRedirects(
            response,
            reverse("apply:iae_eligibility_for_hire", kwargs={"session_uuid": hire_session.name}),
        )
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Un diagnostic d'éligibilité est nécessaire pour déclarer cette embauche.",
                )
            ],
        )

        assert self.job_seeker.job_applications.exists() is False

    def test_as_geiq(self, client, snapshot):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_prescriber=True)
        client.force_login(company.members.first())
        hiring_start_at = timezone.localdate()
        hiring_end_at = hiring_start_at + datetime.timedelta(days=30)
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "contract_form_data": {
                    "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "answer": "OK",
                    "nb_hours_per_week": 5,
                    "planned_training_hours": 6,
                    "contract_type": ContractType.OTHER,
                    "contract_type_details": "Contrat spécifique pour ce test",
                    "qualification_type": QualificationType.CQP,
                    "qualification_level": QualificationLevel.LEVEL_3,
                    "hired_job": company.job_description_through.first().pk,
                },
            },
        )
        confirmation_url = reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name})

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(confirmation_url)
        assertContains(response, f"Déclarer l’embauche de {self.job_seeker.get_inverted_full_name()}")
        assertContains(response, hiring_start_at.strftime("%d/%m/%Y"))
        assertContains(response, hiring_end_at.strftime("%d/%m/%Y"))

        response = client.post(confirmation_url)
        job_application = JobApplication.objects.select_related("job_seeker").get(
            sender=company.members.first(), to_company=company
        )
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.answer == "OK"
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume is None
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at == hiring_end_at
        assert job_application.nb_hours_per_week == 5
        assert job_application.planned_training_hours == 6
        assert job_application.contract_type == ContractType.OTHER
        assert job_application.contract_type_details == "Contrat spécifique pour ce test"
        assert job_application.qualification_type == QualificationType.CQP
        assert job_application.qualification_level == QualificationLevel.LEVEL_3
        assert job_application.hired_job_id == company.job_description_through.first().pk

        assert hire_session.name not in client.session

    def test_as_geiq_missing_data(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True, with_jobs=True)
        GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_prescriber=True)
        client.force_login(company.members.first())
        hiring_start_at = timezone.localdate()
        hiring_end_at = hiring_start_at + datetime.timedelta(days=30)
        hire_session = fake_session_initialization(
            client,
            company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "contract_form_data": {
                    "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                    "answer": "OK",
                    "nb_hours_per_week": 5,
                    "planned_training_hours": 6,
                    "contract_type": "",  # Missing
                    "contract_type_details": "Contrat spécifique pour ce test",
                    "qualification_type": QualificationType.CQP,
                    "qualification_level": QualificationLevel.LEVEL_3,
                    "hired_job": company.job_description_through.first().pk,
                },
            },
        )
        response = client.get(reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))

        response = client.post(reverse("apply:hire_confirmation", kwargs={"session_uuid": hire_session.name}))
        assertRedirects(response, reverse("apply:hire_contract_infos", kwargs={"session_uuid": hire_session.name}))
        assert not JobApplication.objects.exists()


class TestNewHireProcessInfo:
    GEIQ_APPLY_PROCESS_INFO = "Cet espace vous permet d’enregistrer une candidature à traiter plus tard"
    OTHER_APPLY_PROCESS_INFO = "Cet espace vous permet d’enregistrer une nouvelle candidature."

    GEIQ_DIRECT_HIRE_PROCESS_INFO = "Si vous souhaitez créer une candidature à traiter plus tard"
    OTHER_DIRECT_HIRE_PROCESS_INFO = "Pour la création d’une candidature, veuillez vous rendre sur"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        self.geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        self.job_seeker = JobSeekerFactory(jobseeker_profile__nir="")

    def test_as_job_seeker(self, client):
        client.force_login(self.job_seeker)
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.company.pk}), follow=True)
        assert response.status_code == 403
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.geiq.pk}), follow=True)
        assert response.status_code == 403

    def test_as_prescriber(self, client):
        client.force_login(PrescriberFactory())
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.company.pk}), follow=True)
        assert response.status_code == 403
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.geiq.pk}), follow=True)
        assert response.status_code == 403

    def test_as_employer(self, client):
        client.force_login(self.company.members.first())

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.company.pk}), follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        check_nir_for_hire_url = reverse(
            "job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name}
        )
        check_nir_for_sender_url = reverse(
            "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )
        assertRedirects(response, check_nir_for_hire_url)

        response = client.get(check_nir_for_hire_url)
        assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        assertContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)

        response = client.get(check_nir_for_sender_url)
        assertContains(response, self.OTHER_APPLY_PROCESS_INFO)
        assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)

        client.force_login(self.geiq.members.first())

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.geiq.pk}), follow=True)
        job_seeker_session_name_geiq = get_session_name(
            client.session, JobSeekerSessionKinds.GET_OR_CREATE, ignore=[job_seeker_session_name]
        )
        check_nir_for_hire_url = reverse(
            "job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name_geiq}
        )
        check_nir_for_sender_url = reverse(
            "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name_geiq}
        )
        assertRedirects(response, check_nir_for_hire_url)

        response = client.get(check_nir_for_sender_url)
        assertContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)
        response = client.get(check_nir_for_hire_url)
        assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        assertContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)
