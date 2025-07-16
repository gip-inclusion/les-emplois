from functools import partial

from itou.companies.models import Company, CompanyMembership
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.utils.command import BaseCommand, dry_runnable


ATTACH_USER_TO_COMPANY = {
    6311: [3963],
    27928: [5074],
    49547: [6248],
    270735: [3940, 6182],
}

ATTACH_USER_TO_ORGANIZATION = {
    494138: 2333,
}


def sort_company(company, *, job_app):
    company_membership = [m for m in job_app.sender.companymembership_set.all() if m.company == company][0]
    return (
        company.created_at < job_app.created_at,
        company_membership.joined_at < job_app.created_at,
        company.department == job_app.to_company.department,
        company.source == Company.SOURCE_ASP,
        company_membership.is_admin,
    )


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @dry_runnable
    def handle(self, **options):
        for job_app in JobApplication.objects.filter(sender_kind="prescriber", sender_company__isnull=False).order_by(
            "sender"
        ):
            print("JOB APP", job_app.pk)
            print("> Sender:", job_app.sender)
            match len(job_app.sender.prescriberorganization_set.all()):
                case 0:
                    if job_app.sender.company_set.all() or job_app.sender_id in ATTACH_USER_TO_COMPANY:
                        # Convert the user to employer kind
                        if job_app.sender.kind != UserKind.EMPLOYER:
                            print("> > Convert", job_app.sender, "to employer")
                            job_app.sender.kind = UserKind.EMPLOYER
                            job_app.sender.save(update_fields={"kind"})
                        if (
                            job_app.to_company not in job_app.sender.companymembership_set.all()
                            and job_app.sender_id in ATTACH_USER_TO_COMPANY
                        ):
                            # Attach it to the company
                            print("> > Attach", job_app.sender, "to", job_app.to_company)
                            assert job_app.to_company_id in ATTACH_USER_TO_COMPANY[job_app.sender_id], (
                                job_app.to_company_id,
                                ATTACH_USER_TO_COMPANY[job_app.sender_id],
                            )
                            CompanyMembership.objects.create(user=job_app.sender, company=job_app.to_company)
                            ATTACH_USER_TO_COMPANY[job_app.sender_id].remove(job_app.to_company_id)
                            if not ATTACH_USER_TO_COMPANY[job_app.sender_id]:
                                del ATTACH_USER_TO_COMPANY[job_app.sender_id]
                        # Update the job application
                        job_app.sender_kind = SenderKind.EMPLOYER
                        job_app.save(update_fields={"sender_kind", "updated_at"})
                    else:
                        print("> FIXME: NO COMPANY TO CHOOSE FROM")
                case 1:
                    job_app.sender_company = None
                    job_app.sender_prescriber_organization = job_app.sender.prescriberorganization_set.get()
                    job_app.save(update_fields={"sender_company", "sender_prescriber_organization", "updated_at"})
                case _:  # 2 or more
                    print("> FIXME: TOO MANY ORGANIZATIONS TO CHOOSE FROM")

        for job_app in JobApplication.objects.filter(sender_kind="employer", sender_company=None):
            print("JOB APP", job_app.pk)
            print("> Sender:", job_app.sender)
            match len(job_app.sender.company_set.all()):
                case 0:
                    if job_app.sender_id in ATTACH_USER_TO_ORGANIZATION:
                        # Convert the user to prescriber kind
                        if job_app.sender.kind != UserKind.PRESCRIBER:
                            print("> > Convert", job_app.sender, "to prescriber")
                            job_app.sender.kind = UserKind.PRESCRIBER
                            job_app.sender.save(update_fields={"kind"})
                        if (
                            job_app.sender_prescriber_organization
                            not in job_app.sender.prescriberorganization_set.all()
                            and job_app.sender_id in ATTACH_USER_TO_ORGANIZATION
                        ):
                            # Attach it to the organization
                            print("> > Attach", job_app.sender, "to", job_app.sender_prescriber_organization)
                            assert (
                                job_app.sender_prescriber_organization_id
                                == ATTACH_USER_TO_ORGANIZATION[job_app.sender_id]
                            )
                            PrescriberMembership.objects.create(
                                user=job_app.sender, organization=job_app.sender_prescriber_organization
                            )
                            del ATTACH_USER_TO_ORGANIZATION[job_app.sender_id]
                        if job_app.sender_kind != SenderKind.PRESCRIBER:
                            job_app.sender_kind = SenderKind.PRESCRIBER
                            job_app.save(update_fields={"sender_kind", "updated_at"})
                    else:
                        print("> FIXME: NO COMPANY TO CHOOSE FROM")
                case _:  # 1 or more
                    if job_app.to_company in job_app.sender.company_set.all():
                        job_app.sender_company = job_app.to_company
                        job_app.sender_prescriber_organization = None
                        job_app.save(update_fields={"sender_company", "sender_prescriber_organization", "updated_at"})
                    else:
                        sorted_companies = sorted(
                            job_app.sender.company_set.all(), key=partial(sort_company, job_app=job_app), reverse=True
                        )
                        job_app.sender_company = sorted_companies[0]
                        job_app.sender_prescriber_organization = None
                        job_app.save(update_fields={"sender_company", "sender_prescriber_organization", "updated_at"})
