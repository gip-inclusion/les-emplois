import time
from collections import defaultdict
from itertools import batched
from math import ceil

from django.contrib.auth.models import ContentType
from django.db.models import Q

from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.utils.command import BaseCommand
from itou.utils.db import or_queries
from itou.utils.models import PkSupportRemark


CHUNK_SIZE = 500


def analyze_diff(set_from_linked_job_seeker_ids, set_from_assignments):
    """Analyze the differences between the two sets, and return True if we should print details"""
    only_in_linked_job_seeker_ids = list(set_from_linked_job_seeker_ids.difference(set_from_assignments))
    only_in_assignments = list(set_from_assignments.difference(set_from_linked_job_seeker_ids))

    if only_in_linked_job_seeker_ids:
        print(f"ids only found in link_job_seeker_ids: {only_in_linked_job_seeker_ids}")

    for id in only_in_assignments:
        if not User.objects.get(pk=id).is_active:
            # The job seeker has been deactivated, the object (eg. applications) may have been deleted by hand
            # but the assignments are left.
            print(f"⏸️ id {id} was only found in assignments because this job seeker was deactivated")
            only_in_assignments.remove(id)

        remark = PkSupportRemark.objects.filter(
            content_type=ContentType.objects.get_for_model(User), object_id=id
        ).first()
        if remark and f"vers {id}:" in remark.remark:
            # The id was only in assignments because the job seeker was transferred
            # (we transfer assignments but not created_by)
            print(f"⏩ id {id} was only found in assignments because this job seeker was transferred")
            only_in_assignments.remove(id)
    if only_in_assignments:
        print(f"ids only found in assignments: {only_in_assignments}")
    return bool(only_in_linked_job_seeker_ids) or bool(only_in_assignments)


def print_details(prescriber_id, organization_id, from_all_coworkers=False):
    # Code from linked_job_seeker_ids
    job_seeker_filters = [
        Q(created_by_id=prescriber_id, jobseeker_profile__created_by_prescriber_organization=None),
        Q(created_by_id=prescriber_id, jobseeker_profile__created_by_prescriber_organization=organization_id),
    ]
    job_applications_filters = [
        Q(sender_id=prescriber_id, sender_prescriber_organization=None),
        Q(sender_id=prescriber_id, sender_prescriber_organization_id=organization_id),
    ]
    eligibility_diagnosis_filters = [
        Q(author_id=prescriber_id, author_prescriber_organization=None),
        Q(author_id=prescriber_id, author_prescriber_organization_id=organization_id),
    ]

    if from_all_coworkers:
        job_seeker_filters.append(Q(jobseeker_profile__created_by_prescriber_organization_id=organization_id))
        job_applications_filters.append(Q(sender_prescriber_organization_id=organization_id))
        eligibility_diagnosis_filters.append(Q(author_prescriber_organization_id=organization_id))
        print(f"{from_all_coworkers=}")

    created_js = (
        User.objects.filter(kind=UserKind.JOB_SEEKER)
        .filter(or_queries(job_seeker_filters))
        .values_list("pk", flat=True)
    )
    application_js = JobApplication.objects.filter(or_queries(job_applications_filters)).values_list(
        "job_seeker_id", flat=True
    )
    iae_diag_js = EligibilityDiagnosis.objects.filter(or_queries(eligibility_diagnosis_filters)).values_list(
        "job_seeker_id", flat=True
    )
    geiq_diag_js = GEIQEligibilityDiagnosis.objects.filter(or_queries(eligibility_diagnosis_filters)).values_list(
        "job_seeker_id", flat=True
    )

    print(f"Job seekers created by the user: {sorted(created_js)}")
    print(f"Job seekers linked by applications: {sorted(application_js)}")
    print(f"Job seekers linked by iae diag: {sorted(iae_diag_js)}")
    print(f"Job seekers linked by geiq diag: {sorted(geiq_diag_js)}")
    print("-------------------------------\n")


class Command(BaseCommand):
    help = (
        "Temporary command to check wheter `User.objects.linked_job_seekers_ids` is equivalent "
        "to the JobSeekerAssignment objects."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample_size",
            dest="sample_size",
            type=float,
            help="Percentage (from 0 to 100) of prescribers to test",
            default=10,
        )

    def handle(self, **options):
        start_time = time.perf_counter()
        self.logger.info("Script starting!")

        prescribers_pks = list(User.objects.filter(kind=UserKind.PRESCRIBER).values_list("pk", flat=True))
        sample_size = options.get("sample_size")
        selected_prescribers_count = ceil(len(prescribers_pks) * float(sample_size) / 100)
        selected_prescribers_pks = prescribers_pks[:selected_prescribers_count]

        self.logger.info(
            f"{len(prescribers_pks)} prescribers in total. "
            f"Selecting {sample_size}%, that is {len(selected_prescribers_pks)}."
        )

        chunks_count = 0
        chunks_total = ceil(len(selected_prescribers_pks) / CHUNK_SIZE)
        for chunks_count, prescribers_ids in enumerate(batched(selected_prescribers_pks, CHUNK_SIZE)):
            assignments = defaultdict(list)
            for assignment in JobSeekerAssignment.objects.filter(
                professional_id__in=prescribers_ids, company__isnull=True
            ):
                assignments[(assignment.professional_id, assignment.prescriber_organization_id)].append(
                    assignment.job_seeker_id
                )

            memberships = defaultdict(list)
            prescriber_organizations_ids = set()
            for membership in PrescriberMembership.objects.filter(user_id__in=prescribers_ids):
                memberships[membership.user_id].append(membership)
                prescriber_organizations_ids.add(membership.organization_id)

            organization_assignments = defaultdict(list)
            for assignment in JobSeekerAssignment.objects.filter(
                prescriber_organization_id__in=prescriber_organizations_ids
            ):
                organization_assignments[assignment.prescriber_organization_id].append(assignment.job_seeker_id)

            for prescriber_id in prescribers_ids:
                for membership in memberships[prescriber_id]:
                    # Prescriber only ("Mes candidats")
                    prescriber_job_seekers_ids = set(
                        sorted(list(User.objects.linked_job_seeker_ids(membership.user, membership.organization)))
                    )
                    prescriber_assignments_job_seekers_ids = set(
                        assignments[(prescriber_id, membership.organization_id)]
                    ).union(set(assignments[(prescriber_id, None)]))
                    if prescriber_job_seekers_ids != prescriber_assignments_job_seekers_ids:
                        print(
                            f"❌[PRESCRIBER] Mismatch with prescriber={prescriber_id}, "
                            f"organization={membership.organization_id}"
                        )
                        if analyze_diff(prescriber_job_seekers_ids, prescriber_assignments_job_seekers_ids):
                            print_details(prescriber_id, membership.organization_id)

                    # Prescriber's organization ("Tous les candidats de ma structure")
                    organization_job_seekers_ids = set(
                        sorted(
                            list(
                                User.objects.linked_job_seeker_ids(
                                    membership.user, membership.organization, from_all_coworkers=True
                                )
                            )
                        )
                    )
                    organization_assignments_job_seekers_ids = set(
                        organization_assignments[membership.organization_id]
                    ).union(set(assignments[(prescriber_id, None)]))

                    if organization_job_seekers_ids != organization_assignments_job_seekers_ids:
                        print(
                            f"❌[ORGANIZATION] Mismatch with prescriber={prescriber_id}, "
                            f"organization={membership.organization_id}"
                        )
                        if analyze_diff(organization_job_seekers_ids, organization_assignments_job_seekers_ids):
                            print_details(prescriber_id, membership.organization_id, from_all_coworkers=True)

            print(
                f"{chunks_count / chunks_total * 100:.2f}% - elapsed time: {time.perf_counter() - start_time:.2f}s",
                end="\r",
            )
