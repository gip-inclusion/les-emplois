import random

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.nexus.enums import NexusStructureKind, Service
from itou.nexus.models import NexusUser
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.models import User
from itou.utils import triggers
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.nexus.factories import NexusMembershipFactory, NexusUserFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, ProfessionalFactory


def test(tmp_path):
    matching_prescriber_kinds = [
        kind
        for kind in NexusStructureKind
        if kind in PrescriberOrganizationKind
        and kind not in [PrescriberOrganizationKind.OTHER, PrescriberOrganizationKind.FT]  # specific behaviors
    ]
    matching_company_kinds = [
        kind
        for kind in NexusStructureKind
        if kind in CompanyKind and kind not in [CompanyKind.EA, CompanyKind.EATT]  # No more membership on those
    ]

    # NexusUser with no User
    # One membership in dora, structure exists in Emplois
    # create user and membership
    nexus_user_1 = NexusUserFactory(source=Service.DORA)
    nexus_structure_1 = NexusMembershipFactory(
        user=nexus_user_1,
        source=Service.DORA,
        structure__kind=random.choice(matching_prescriber_kinds),
    ).structure
    PrescriberOrganizationFactory(
        siret=nexus_structure_1.siret,
        kind=nexus_structure_1.kind,
    )

    # FT NexusUser with matching user
    # membership on a siret that does not exist
    # Don't create the structure
    nexus_user_2 = NexusUserFactory(source=Service.DORA, email="prénom.nom@francetravail.fr")
    ProfessionalFactory(email=nexus_user_2.email)
    NexusMembershipFactory(
        user=nexus_user_2,
        source=Service.DORA,
        structure__kind=NexusStructureKind.FT,
    )

    # NexusUser with matching User
    # One membership in dora that exists in emplois
    # nothing to do
    nexus_user_3 = NexusUserFactory(source=Service.DORA)
    user_3 = ProfessionalFactory(email=nexus_user_3.email)
    nexus_structure_3 = NexusMembershipFactory(
        user=nexus_user_3,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
    ).structure
    CompanyMembershipFactory(
        company__siret=nexus_structure_3.siret,
        company__kind=nexus_structure_3.kind,
        user=user_3,
    )

    # NexusUser with matching User
    # 2 memberships in dora, only one kind exits in Emplois, no membership yet
    # create the membership in les emplois on the kind that exists
    nexus_user_4 = NexusUserFactory(source=Service.DORA)
    ProfessionalFactory(email=nexus_user_4.email)
    nexus_structure_4a = NexusMembershipFactory(
        user=nexus_user_4,
        source=Service.DORA,
        structure__kind=random.choice(matching_prescriber_kinds),
    ).structure
    nexus_structure_4b = NexusMembershipFactory(
        user=nexus_user_4,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
        structure__siret=nexus_structure_4a.siret,
    ).structure
    CompanyFactory(
        siret=nexus_structure_4b.siret,
        kind=nexus_structure_4b.kind,
    )

    # NexusUser with matching user
    nexus_user_5 = NexusUserFactory(source=Service.DORA)
    ProfessionalFactory(email=nexus_user_5.email)
    # One membership in dora kind CCAS_CIAS, CCAS exists in les emplois
    nexus_structure_5a = NexusMembershipFactory(
        user=nexus_user_5,
        source=Service.DORA,
        structure__kind=NexusStructureKind.CCAS_CIAS,
    ).structure
    PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.CCAS, siret=nexus_structure_5a.siret)
    # One membership in dora kind COD, OCD existd in les emplois (the enum value is different)
    nexus_structure_5b = NexusMembershipFactory(
        user=nexus_user_5,
        source=Service.DORA,
        structure__kind=NexusStructureKind.OCD,
    ).structure
    PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.ODC, siret=nexus_structure_5b.siret)

    # NexusUser with matching user
    # One membership in dora that exists in emplois, prescriber org disabled
    # One membership in dora that exists in emplois, company disabled
    # both emplois memberhips are activated again
    nexus_user_6 = NexusUserFactory(source=Service.DORA)
    user_6 = ProfessionalFactory(email=nexus_user_6.email)
    nexus_structure_6a = NexusMembershipFactory(
        user=nexus_user_6,
        source=Service.DORA,
        structure__kind=random.choice(matching_prescriber_kinds),
    ).structure
    PrescriberMembershipFactory(
        user=user_6,
        organization__kind=nexus_structure_6a.kind,
        organization__siret=nexus_structure_6a.siret,
        is_active=False,
    )
    nexus_structure_6b = NexusMembershipFactory(
        user=nexus_user_6,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
    ).structure
    CompanyMembershipFactory(
        user=user_6,
        company__kind=nexus_structure_6b.kind,
        company__siret=nexus_structure_6b.siret,
        is_active=False,
    )

    # NexusUser with matching user
    # dora structure siret does not exists
    # create structure kind other
    nexus_user_7 = NexusUserFactory(source=Service.DORA)
    ProfessionalFactory(email=nexus_user_7.email)
    nexus_structure_7 = NexusMembershipFactory(
        user=nexus_user_7,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
    ).structure

    # Same as above with another email (but same siret)
    # don't create again the structure
    nexus_user_8 = NexusUserFactory(source=Service.DORA)
    ProfessionalFactory(email=nexus_user_8.email)
    nexus_structure_8 = NexusMembershipFactory(
        user=nexus_user_8,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
        structure__siret=nexus_structure_7.siret,
    ).structure

    # NexusUser with matching user
    # dora structure matches company old siret
    nexus_user_9 = NexusUserFactory(source=Service.DORA)
    # This user has an uppercase email
    user_9 = ProfessionalFactory(email=nexus_user_9.email.upper())
    nexus_structure_9 = NexusMembershipFactory(
        user=nexus_user_9,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
    ).structure
    company_9 = CompanyMembershipFactory(
        user=user_9,
        company__kind=nexus_structure_9.kind,
        company__siret=nexus_structure_9.siret,
    ).company
    # fill fields_history
    with transaction.atomic(), triggers.fake_context():
        company_9.siret = "10000000000000"
        company_9.save()

    # NexusUser with matching user
    # dora structure has no siret : ignore it
    nexus_user_10 = NexusUserFactory(source=Service.DORA)
    # This NexusUser has an uppercase email
    nexus_user_10.email = nexus_user_10.email.upper()
    nexus_user_10.save()
    ProfessionalFactory(email=nexus_user_10.email)
    NexusMembershipFactory(
        user=nexus_user_10,
        source=Service.DORA,
        structure__siret=None,
    )

    # NexusUser matching a job seeker in les empls:  ignore him
    nexus_user_11 = NexusUserFactory(source=Service.DORA)
    NexusMembershipFactory(
        user=nexus_user_11,
        source=Service.DORA,
        structure__kind=random.choice(matching_company_kinds),
    )
    JobSeekerFactory(email=nexus_user_11.email)

    # ---------------------------------------------------
    # Run the command

    creation_cutoff = timezone.now()
    email_list = tmp_path / "email_list.txt"
    email_list.write_text(
        "\n".join(
            # capitalize emails to ensure we don't care about the case in the list
            [email.capitalize() for email in NexusUser.objects.values_list("email", flat=True)]
            + ["email_with_no_nexus_user@mailinator.com"]
        )
    )

    call_command("create_dora_users", file_path=str(email_list), write_outputs=False)
    assert User.objects.filter(date_joined__gte=creation_cutoff).count() == 0
    assert PrescriberOrganization.objects.filter(updated_at__gte=creation_cutoff).count() == 0
    assert Company.objects.filter(updated_at__gte=creation_cutoff).count() == 0
    assert PrescriberMembership.objects.filter(updated_at__gte=creation_cutoff).count() == 0
    assert CompanyMembership.objects.filter(updated_at__gte=creation_cutoff).count() == 0

    call_command("create_dora_users", file_path=str(email_list), wet_run=True, write_outputs=False)

    assertQuerySetEqual(
        User.objects.filter(date_joined__gte=creation_cutoff),
        [nexus_user_1.email],
        lambda user: user.email,
        ordered=False,
    )
    assert Company.objects.filter(updated_at__gte=creation_cutoff).count() == 0
    assertQuerySetEqual(
        PrescriberMembership.objects.filter(updated_at__gte=creation_cutoff).select_related("user", "organization"),
        [
            (nexus_user_1.email, nexus_structure_1.kind, nexus_structure_1.siret),
            (nexus_user_5.email, PrescriberOrganizationKind.CCAS, nexus_structure_5a.siret),
            (nexus_user_5.email, PrescriberOrganizationKind.ODC, nexus_structure_5b.siret),
            (nexus_user_6.email, nexus_structure_6a.kind, nexus_structure_6a.siret),
            (nexus_user_7.email, PrescriberOrganizationKind.OTHER, nexus_structure_7.siret),
            (nexus_user_8.email, PrescriberOrganizationKind.OTHER, nexus_structure_8.siret),
        ],
        lambda membership: (membership.user.email, membership.organization.kind, membership.organization.siret),
        ordered=False,
    )
    assertQuerySetEqual(
        CompanyMembership.objects.filter(updated_at__gte=creation_cutoff).select_related("user", "company"),
        [
            (nexus_user_4.email, nexus_structure_4b.kind, nexus_structure_4b.siret),
            (nexus_user_6.email, nexus_structure_6b.kind, nexus_structure_6b.siret),
        ],
        lambda membership: (membership.user.email, membership.company.kind, membership.company.siret),
        ordered=False,
    )

    new_org = PrescriberOrganization.objects.filter(updated_at__gte=creation_cutoff).get()
    assert new_org.siret == nexus_structure_7.siret
    assert new_org.kind == PrescriberOrganizationKind.OTHER
    assert new_org.authorization_status == PrescriberAuthorizationStatus.NOT_REQUIRED
