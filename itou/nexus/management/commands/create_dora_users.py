import enum
from collections import Counter

from itoutils.django.commands import dry_runnable

from itou.companies.models import Company, CompanyMembership
from itou.nexus.enums import NexusStructureKind, Service
from itou.nexus.models import NexusUser
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.command import BaseCommand


class Scenario(enum.Enum):
    """All encountered cases after creating missing users and memberships"""

    # The user has one membership in DORA and one in les emplois
    ONE_MEMBERSHIP_MATCH = 1
    # The user is from FT and has more than one membership on either side,
    # we don't really care since a FT user will be associated to their organization when logging in
    FT_WITH_ISSUES = 2
    # The user has more than one membership, and all dora memberships exist in les emplois
    MULTI_MEMBERSHIPS_ALL_MATCH = 3
    # The user is missing one or more DORA memberships, and has no les emplois membership (blocked user)
    MISSING_MATCH_NO_MEMBERSHIP = 4
    # The user is missing one or more DORA memberships, but has a least one les emplois membership
    MISSING_MATCH_WITH_MEMBERSHIP = 5
    # The user has no NexusUser object
    MISSING_NEXUS_USER = 6


class Command(BaseCommand):
    """This command will allow us to import the recently actives Dora users.

    Given a list of emails it will:
     - Create Users based DORA's synced NexusUsers
     - Create memberships when we find a match with the NexusMemberships and NexusStructures.
     - Write log files for all users that might have issues when being redirected from DORA.
    """

    ATOMIC_HANDLE = True
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Perform the user creation",
        )
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Path of the email list file to import",
        )
        parser.add_argument(
            "--write_outputs",
            dest="write_outputs",
            action="store_true",
        )

    def parse_file(self, file_path):
        with open(file_path) as f:
            emails_list = f.readlines()
        return [email.strip().lower() for email in emails_list]

    def display_structure(self, structure, old_siret=None):
        return f"{old_siret or structure.siret} | {structure.kind or 'N/A':<8} | {structure.name}"

    def find_structure_smart_match(self, nexus_siret):
        if not nexus_siret:
            return

        return self.emplois_full_structure_list.get((nexus_siret, PrescriberOrganizationKind.OTHER))

    def build_user(self, nexus_user):
        return User(
            kind=UserKind.PROFESSIONAL,
            identity_provider=IdentityProvider.PRO_CONNECT,
            first_name=nexus_user.first_name,
            last_name=nexus_user.last_name,
            email=nexus_user.email,
            username=nexus_user.id,  # Will be overwritten at login
        )

    def build_membership(self, user, structure):
        if isinstance(structure, Company):
            return CompanyMembership(user=user, company=structure)
        if isinstance(structure, PrescriberOrganization):
            return PrescriberMembership(user=user, organization=structure)
        raise ValueError(f"Invalid type of structure={structure}")

    def process_logs(self, print_str, scenario, filename=None):
        scenario_logs = self.logs[scenario]
        print(print_str, len(scenario_logs))

        if filename and self.write_outputs:
            with open("shared_bucket/" + filename, "w") as ff:
                for elmt in scenario_logs:
                    ff.write(elmt)

    def process_email(self, email):
        # local vars to help computing the scenario
        missing_memberships = False
        found_emplois_user = False

        # Create a detailed log of the process
        log = "--------------------------------\n"
        log += f"email: {email}\n"

        # Find the matching NexusUser
        nexus_user = self.nexus_users.get(email)
        log += f"found nexus account: {bool(nexus_user)}\n"

        # Find the matching User
        emplois_user = self.emplois_users.get(email)
        found_emplois_user = bool(emplois_user)
        log += f"found emplois account: {found_emplois_user}\n"

        # List dora memberships
        linked_nexus_structures = []
        if nexus_user:
            linked_nexus_structures += [m.structure for m in nexus_user.memberships.all()]

        # List emplois memberships
        linked_emplois_structures = []
        if emplois_user:
            linked_emplois_structures += [m.company for m in emplois_user.companymembership_set.all()]
            linked_emplois_structures += [m.organization for m in emplois_user.prescribermembership_set.all()]

        # build a list of siret/kind tuples from the user's emplois memberships
        linked_emplois_structures_tuples = []
        if emplois_user:
            log += "emplois memberships:\n"
        for structure in linked_emplois_structures:
            linked_emplois_structures_tuples.append((structure.siret, structure.kind))
            log += f"   {'':<16}{self.display_structure(structure)}\n"
            # look for old sirets on companies
            for history in getattr(structure, "fields_history", []):
                if old_siret := history["before"].get("siret"):
                    linked_emplois_structures_tuples.append((old_siret, structure.kind))
                    log += f"   {'':<16}{self.display_structure(structure, old_siret=old_siret)}\n"
        if linked_emplois_structures_tuples:
            linked_emplois_structures_sirets = set(list(zip(*linked_emplois_structures_tuples))[0])
        else:
            linked_emplois_structures_sirets = set([])

        if nexus_user is None:
            # nothing to do (we cannot create the User instance without a NexusUser)
            self.logs[Scenario.MISSING_NEXUS_USER].append(log)
            return

        # Now we start doing thing about this user
        # -----------------------------------------------------------------------------------------

        if emplois_user is None:
            # We need to create a user
            emplois_user = self.build_user(nexus_user)
            self.users_to_create.append(emplois_user)

        # Run through the synced memberships from dora
        log += "dora memberships:\n"
        no_match_sirets = []
        for nexus_structure in linked_nexus_structures:
            if not nexus_structure.siret:
                log += f"   {'IGNORE NO SIRET':<16}{self.display_structure(nexus_structure)}\n"
                missing_memberships = True
                continue

            # Fix nexus kind to emplois kind matching (see STRUCTURE_KIND_MAPPING)
            nexus_kind = nexus_structure.kind
            if nexus_kind == NexusStructureKind.CCAS_CIAS:
                nexus_kind = PrescriberOrganizationKind.CCAS
            if nexus_kind == NexusStructureKind.OCD:
                nexus_kind = PrescriberOrganizationKind.ODC  # the string isn't the same....

            # Is there the same membership in les emplois ?
            if (nexus_structure.siret, nexus_kind) in linked_emplois_structures_tuples:
                # Yes, nothing to do !
                log += f"   {'EXIST':<16}{self.display_structure(nexus_structure)}\n"

            # Can we find the matching structure in les emplois ?
            elif structure := self.emplois_full_structure_list.get((nexus_structure.siret, nexus_kind)):
                # Yes, we will create a membership on it
                log += f"   {'CREATE':<16}{self.display_structure(nexus_structure)}\n"
                # update linked_emplois_structures_* vars
                linked_emplois_structures_tuples.append((nexus_structure.siret, nexus_kind))
                linked_emplois_structures_sirets.add(nexus_structure.siret)
                linked_emplois_structures.append(structure)
                # Add to memberships to create
                self.memberships_to_create.append(self.build_membership(emplois_user, structure))

            # Does the user already has a membership with this siret ?
            elif nexus_structure.siret in linked_emplois_structures_sirets:
                # We couldn't match the structure, but the user is already linked to this siret don't no anything
                log += f"   {'EXIST (≠kind)':<16}{self.display_structure(nexus_structure)}\n"

            # The user has no membership with this siret, we need to fallback somewhere.
            # We don't want to give the user too much permissions in the plateforme
            # so authorized prescriber organizations and companies are not what we want.
            # Can we find a PrescriberOrganization with the OTHER kind ?
            elif structure := self.emplois_full_structure_list.get(
                (nexus_structure.siret, PrescriberOrganizationKind.OTHER)
            ):
                # We know the user isn't a member yet since the siret isn't in linked_emplois_structures_sirets
                # Create the memberships
                log += f"   {'CREATE (kind=Autre)':<16}{self.display_structure(nexus_structure)}\n"
                # update linked_emplois_structures_* vars
                linked_emplois_structures_tuples.append((nexus_structure.siret, nexus_kind))
                linked_emplois_structures_sirets.add(nexus_structure.siret)
                linked_emplois_structures.append(structure)
                # Add to memberships to create
                self.memberships_to_create.append(self.build_membership(emplois_user, structure))

            # Does this siret exist in les emplois ?
            elif (self.emplois_siret_counter.get(nexus_structure.siret, 0) == 0) and (
                nexus_kind != NexusStructureKind.FT
            ):
                # No -> create a unauthorized PrescriberOrganization and the membership
                structure = PrescriberOrganization(
                    siret=nexus_structure.siret,
                    kind=PrescriberOrganizationKind.OTHER,
                    authorization_status=PrescriberAuthorizationStatus.NOT_REQUIRED,
                    phone=nexus_structure.phone,
                    email=nexus_structure.email,
                    website=nexus_structure.website,
                    description=nexus_structure.description,
                    address_line_1=nexus_structure.address_line_1,
                    address_line_2=nexus_structure.address_line_2,
                    post_code=nexus_structure.post_code,
                    city=nexus_structure.city,
                    department=nexus_structure.department,
                    name=nexus_structure.name,
                )
                try:
                    # Set geocoding.
                    structure.geocode_address()
                except GeocodingDataError:
                    # Could not find the address, don't crash and let the coords empty
                    pass
                self.org_to_create.append(structure)
                log += f"   {'CREATE (new org)':<16}{self.display_structure(nexus_structure)}\n"

                # Add the structure to the list of emplois structures to prevent creating it for another user
                self.emplois_full_structure_list[(nexus_structure.siret, PrescriberOrganizationKind.OTHER)] = structure
                # update linked_emplois_structures_* vars
                linked_emplois_structures_tuples.append((nexus_structure.siret, nexus_kind))
                linked_emplois_structures_sirets.add(nexus_structure.siret)
                linked_emplois_structures.append(structure)
                # Add to memberships to create
                self.memberships_to_create.append(self.build_membership(emplois_user, structure))

            # We could not find the same structure, but another one exists with the same siret and
            # high privileges. Manually handle thoses
            else:
                missing_memberships = True
                log += f"   {'NO MATCH':<16}{self.display_structure(nexus_structure)}\n"
                no_match_sirets.append(nexus_structure.siret)

        # For all structures wh we didn't find an exact or unique match, log all available choices in les emplois
        if no_match_sirets:
            log += "emplois structure with non matched sirets:\n"
            for (siret, kind), structure in self.emplois_full_structure_list.items():
                for no_match_siret in no_match_sirets:
                    if no_match_siret == siret:
                        log += f"   {'':<16}{self.display_structure(structure)}\n"

        # Put the log in the relevent scenario
        if missing_memberships:
            if email.endswith("francetravail.fr"):
                self.logs[Scenario.FT_WITH_ISSUES].append(log)
            elif len(linked_emplois_structures) > 0:
                self.logs[Scenario.MISSING_MATCH_WITH_MEMBERSHIP].append(log)
            else:
                self.logs[Scenario.MISSING_MATCH_NO_MEMBERSHIP].append(log)
        else:
            if len(linked_nexus_structures) == len(linked_emplois_structures) == 1:
                self.logs[Scenario.ONE_MEMBERSHIP_MATCH].append(log)
            elif email.endswith("francetravail.fr"):
                self.logs[Scenario.FT_WITH_ISSUES].append(log)
            else:
                self.logs[Scenario.MULTI_MEMBERSHIPS_ALL_MATCH].append(log)

    @dry_runnable
    def handle(self, *, file_path, wet_run, write_outputs, **options):
        self.write_outputs = write_outputs
        dora_emails = self.parse_file(file_path)

        # Retrieve nexus users
        # -----------------------------------------------------------------------------------------
        # We will only create a User if we find the email in a NexusUser
        # (because we need the first_name and last_name)
        self.nexus_users = {
            user.email.lower(): user
            for user in NexusUser.objects.filter(email__in=dora_emails, source=Service.DORA).prefetch_related(
                "memberships__structure"
            )
        }

        # Retrive emplois users
        # -----------------------------------------------------------------------------------------
        # To know which users are missing, and to fill user_id fields in new memberships
        self.emplois_users = {
            user.email.lower(): user
            for user in User.objects.filter(email__in=dora_emails).prefetch_related(
                "prescribermembership_set", "companymembership_set"
            )
        }

        # Build a dict with of all prescriber organizations and companies using the (siret, kind) tuple as dict key
        # -----------------------------------------------------------------------------------------
        # This will allow us to find a the local structure using a NexusStructure siret and kind
        self.emplois_full_structure_list = {(org.siret, org.kind): org for org in PrescriberOrganization.objects.all()}
        for company in Company.objects.all():
            self.emplois_full_structure_list[(company.siret, company.kind)] = company
            # look for old sirets on companies
            for history in company.fields_history:
                if old_siret := history["before"].get("siret"):
                    self.emplois_full_structure_list[(old_siret, company.kind)] = company

        # Count how many structures have a given siret.
        # -----------------------------------------------------------------------------------------
        self.emplois_siret_counter = Counter([siret for (siret, kind) in self.emplois_full_structure_list])

        self.users_to_create = []
        self.org_to_create = []
        self.memberships_to_create = []
        self.logs = {scenario: [] for scenario in Scenario}

        for email in dora_emails:
            self.process_email(email)

        # Create or print the command result
        prescriber_memberships_to_create = [
            m for m in self.memberships_to_create if isinstance(m, PrescriberMembership)
        ]
        company_memberships_to_create = [m for m in self.memberships_to_create if isinstance(m, CompanyMembership)]
        print(f"Utilisateurs dora: {len(dora_emails)}")
        if wet_run:
            User.objects.bulk_create(self.users_to_create)
            print(f"Created {len(self.users_to_create)} Users")
            PrescriberOrganization.objects.bulk_create(self.org_to_create)
            print(f"Created {len(self.org_to_create)} PrescriberOrganizations")
            PrescriberMembership.include_inactive.bulk_create(
                prescriber_memberships_to_create,
                update_conflicts=True,
                update_fields=["is_active", "updated_at"],  # Activate any existing deactivated membership
                unique_fields=["user", "organization"],
            )
            print(f"Created {len(prescriber_memberships_to_create)} PrescriberMemberships")
            CompanyMembership.include_inactive.bulk_create(
                company_memberships_to_create,
                update_conflicts=True,
                update_fields=["is_active", "updated_at"],  # Activate any existing deactivated membership
                unique_fields=["user", "company"],
            )
            print(f"Created {len(company_memberships_to_create)} CompanyMemberships")
        else:
            print(f"Would create {len(self.users_to_create)} Users")
            print(f"Would create {len(self.org_to_create)} PrescriberOrganizations")
            print(f"Would create {len(prescriber_memberships_to_create)} PrescriberMemberships")
            print(f"Would create {len(company_memberships_to_create)} CompanyMemberships")

        # Process logs and display counts
        print("-----------------------------------------------------------------------------------------")
        self.process_logs(
            "nbr comptes avec une seule structure identique des 2 coté:",
            Scenario.ONE_MEMBERSHIP_MATCH,
        )

        self.process_logs(
            "nbr comptes ft avec un soucis mais qui pourront se connecter:",
            Scenario.FT_WITH_ISSUES,
            "dora_1_ft_users_with_issues.txt",
        )

        self.process_logs(
            "nbr comptes avec plusieurs structures (dora ⊆ emplois):",
            Scenario.MULTI_MEMBERSHIPS_ALL_MATCH,
            "dora_2_multiple_memberships.txt",
        )

        self.process_logs(
            "nbr comptes avec au moins une structure dora absente (aucun rattachement côté emplois):",
            Scenario.MISSING_MATCH_NO_MEMBERSHIP,
            "dora_3_no_emplois_membership.txt",
        )

        self.process_logs(
            "nbr comptes avec au moins une structure dora absente (avec un rattachement côté emplois):",
            Scenario.MISSING_MATCH_WITH_MEMBERSHIP,
            "dora_4_with_emplois_membership.txt",
        )

        self.process_logs(
            "nbr compte non traités (pas de synchro nexus):",
            Scenario.MISSING_NEXUS_USER,
            "dora_5_missing_nexus_users.txt",
        )
