"""
Generate fake data based on global Itou's fixtures.
You can use it with the quick login accounts located on the header banner.
Employer's account: test+cap@inclusion.beta.gouv.fr
Labor inspector's account: test+ddets@inclusion.beta.gouv.fr
"""

import random
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

import itou.users.enums as users_enums
from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.institutions.models import Institution
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import Calendar, EvaluationCampaign, create_campaigns_and_calendar
from itou.users.models import User


NAMES = [
    ("Gustave", "Loiseau", "187104712403340", "703059J"),
    ("Aristide", "Filoselle", "187103415217885", "401486E"),
    ("Oliveria", "Da Figueira", "187102017128676", "354471C"),
    ("Fan", "Se-Yeng", "187102531808302", "145793B"),
    ("Archibald", "Haddock", "187107317012993", "103819B"),
    ("Bianca", "Castafiore", "287103404102922", "50704F"),
    ("Mohammed", "Ben Kalish Ezab", "187105714612783", "476261C"),
    ("Tryphon", "Tournesol", "187105012012584", "321089E"),
    ("Bunji", "Kuraki", "187101300806442", "298096C"),
    ("Roberto", "Rastapopoulos", "187107922316551", "424548G"),
    ("Séraphin", "Lampion", "187104308500783", "491405D"),
    ("Allan", "Thompson", "187101033733471", "391055C"),
    ("Diego", "le Navarrais", "187101703338725", "718757J"),
    ("Igor", "Wagner", "187107823832946", "621359J"),
    ("Frank", "Wolff", "187106129833161", "644055J"),
    ("Tristan", "Bior", "187106539602337", "355357E"),
    ("Émile", "Vanneau", "187102117208427", "354895F"),
    ("Jean-Loup", "de La Batellerie", "187109413107670", "354895D"),
]


def generate_approval_number():
    return f"{Approval.ASP_ITOU_PREFIX}" + f"{random.randint(1000, 9999999)}".zfill(7)


def load_data():
    now = timezone.now()
    evaluated_period_start_at = now - relativedelta(months=3)
    evaluated_period_end_at = now - relativedelta(months=1)
    adversarial_stage_start = now.date() + relativedelta(weeks=6)
    datetime_within_period_range = evaluated_period_end_at - relativedelta(weeks=2)

    created_job_applications_pks = []

    employer = User.objects.get(email="test+cap@inclusion.beta.gouv.fr")
    controlled_siaes = employer.company_set.all()
    assert controlled_siaes.count() == 5
    total_administrative_criteria = AdministrativeCriteria.objects.count()
    level_to_criteria_pks = dict(
        AdministrativeCriteria.objects.values("level").annotate(pks=ArrayAgg("pk")).values_list("level", "pks")
    )

    users = User.objects.filter(username__startswith="siae_evaluations_")
    with transaction.atomic():
        users.delete()
        EvaluationCampaign.objects.all().delete()
        Calendar.objects.all().delete()

    # We can't use factories here because FactoryBoy is not installed in Review app and Demo environments.
    for i in range(1, total_administrative_criteria):
        controlled_siae = controlled_siaes[i // 4]
        with transaction.atomic():
            first_name, last_name, nir, pe_id = NAMES[i - 1]
            job_seeker = User.objects.create(
                first_name=first_name,
                last_name=last_name,
                username=f"siae_evaluations_{i}",
                kind=users_enums.KIND_JOB_SEEKER,
                title=random.choice(users_enums.Title.values),
            )
            job_seeker.jobseeker_profile.nir = nir
            job_seeker.jobseeker_profile.pole_emploi_id = pe_id
            job_seeker.jobseeker_profile.save(update_fields=["nir", "pole_emploi_id"])
            level = str((i % 2) + 1)
            # See AdministrativeCriteriaForm
            level2_criteria_count = 2 if controlled_siae.kind in [CompanyKind.AI, CompanyKind.ETTI] else 3
            min_selected_criteria = 1 if level == AdministrativeCriteriaLevel.LEVEL_1 else level2_criteria_count
            pks_list = random.sample(level_to_criteria_pks[level], k=random.randint(min_selected_criteria, 4))

            AdministrativeCriteria.objects.filter(pk__in=pks_list)
            eligibility_diagnosis = EligibilityDiagnosis.objects.create(
                author=employer,
                author_kind=users_enums.KIND_EMPLOYER,
                author_siae=controlled_siae,
                job_seeker=job_seeker,
                created_at=datetime_within_period_range,
            )
            for criterion_pk in pks_list:
                eligibility_diagnosis.administrative_criteria.add(criterion_pk)
            approval = Approval.objects.create(
                user=job_seeker,
                number=generate_approval_number(),
                start_at=datetime_within_period_range.date(),
                end_at=Approval.get_default_end_date(datetime_within_period_range.date()),
                eligibility_diagnosis=eligibility_diagnosis,
                created_at=datetime_within_period_range,
            )
            created_job_applications_pks += [
                JobApplication.objects.create(
                    approval=approval,
                    eligibility_diagnosis=eligibility_diagnosis,
                    hiring_start_at=datetime_within_period_range.date(),
                    created_at=datetime_within_period_range,
                    job_seeker=job_seeker,
                    sender_company=controlled_siae,
                    sender=employer,
                    sender_kind=users_enums.KIND_EMPLOYER,
                    state=JobApplicationState.ACCEPTED,
                    to_company=controlled_siae,
                ).id
            ]

    institution = Institution.objects.get(pk=2)
    job_applications = JobApplication.objects.filter(pk__in=created_job_applications_pks)

    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"), transaction.atomic():
        create_campaigns_and_calendar(evaluated_period_start_at, evaluated_period_end_at, adversarial_stage_start)
        evaluation_campaign = EvaluationCampaign.objects.get(institution=institution)

        # eligible_job_applications must return a queryset, not a list.
        with (
            mock.patch(
                "itou.siae_evaluations.models.EvaluationCampaign.eligible_job_applications",
                return_value=job_applications,
            ),
            mock.patch(
                "itou.siae_evaluations.enums.EvaluationJobApplicationsBoundariesNumber.SELECTION_PERCENTAGE", 100
            ),
            mock.patch(
                "itou.siae_evaluations.models.EvaluationCampaign.number_of_siaes_to_select",
                return_value=controlled_siaes.count(),
            ),
        ):
            evaluation_campaign.populate(timezone.now())
