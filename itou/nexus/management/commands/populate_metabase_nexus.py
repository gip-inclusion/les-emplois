"""
Populate metabase database with data for nexus analysis

All the required code is maintained in this command so that we can easily re-use it in
the other projects.
"""

import logging

import psycopg
import tenacity
from django.conf import settings
from django.utils import timezone
from psycopg import sql

from itou.companies.models import Company, CompanyMembership
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

SOURCE = "emplois-de-linclusion"  # Change in each product
USER_TABLE = "users"
MEMBERSHIPS_TABLE = "memberships"
STRUCTURES_TABLE = "structures"


def get_connection():
    return psycopg.connect(
        host=settings.NEXUS_METABASE_DB_HOST,
        port=settings.NEXUS_METABASE_DB_PORT,
        dbname=settings.NEXUS_METABASE_DB_DATABASE,
        user=settings.NEXUS_METABASE_DB_USER,
        password=settings.NEXUS_METABASE_DB_PASSWORD,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=5,
        keepalives_count=5,
    )


def create_table(reset=False):
    # Naive function because we don't need over engineering here yet
    with get_connection() as conn, conn.cursor() as cursor:
        if reset:
            cursor.execute(f"DROP TABLE IF EXISTS {USER_TABLE}")
            cursor.execute(f"DROP TABLE IF EXISTS {MEMBERSHIPS_TABLE}")
            cursor.execute(f"DROP TABLE IF EXISTS {STRUCTURES_TABLE}")
        cursor.execute(f"""
            CREATE TABLE {USER_TABLE} (
                source              text NOT NULL,
                id_source           text NOT NULL,
                id_unique           text NOT NULL,
                nom                 text NOT NULL,
                prénom              text NOT NULL,
                email               text NOT NULL,
                téléphone           text NOT NULL,
                dernière_connexion  timestamp with time zone,
                auth                text NOT NULL,
                type                text NOT NULL,
                mise_à_jour         timestamp with time zone
            )
            """)
        cursor.execute(f"""
            CREATE TABLE {MEMBERSHIPS_TABLE} (
                source                  text NOT NULL,
                user_id_unique          text NOT NULL,
                structure_id_unique     text NOT NULL,
                role                    text NOT NULL,
                mise_à_jour             timestamp with time zone
            )
            """)
        cursor.execute(f"""
            CREATE TABLE {STRUCTURES_TABLE} (
                source      text NOT NULL,
                id_source   text NOT NULL,
                id_unique   text NOT NULL,
                siret       text,
                nom         text NOT NULL,
                type        text NOT NULL,
                code_insee  text,
                adresse     text,
                code_postal text,
                latitude    double precision,
                longitude   double precision,
                email       text NOT NULL,
                téléphone   text NOT NULL,
                mise_à_jour timestamp with time zone
            )
            """)


def populate_table(table_name, table_columns, serializer, querysets):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"DELETE FROM {table_name} WHERE source = '{SOURCE}'")
        for queryset in querysets:
            with cur.copy(
                sql.SQL("COPY {table_name} ({fields}) FROM STDIN WITH (FORMAT BINARY)").format(
                    table_name=sql.Identifier(table_name),
                    fields=sql.SQL(",").join(
                        [sql.Identifier(name) for name in table_columns.keys()],
                    ),
                )
            ) as copy:
                copy.set_types(table_columns.values())
                for row in queryset.iterator():
                    copy.write_row(serializer(row))


def log_retry_attempt(retry_state):
    logger.info("Attempt failed with outcome=%s", retry_state.outcome)


class Command(BaseCommand):
    help = "Populate nexus metabase database."

    def populate_users(self):
        queryset = User.objects.filter(
            is_active=True,
            kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER],
            email__isnull=False,
        )

        def serializer(user):
            return [
                SOURCE,
                str(user.pk),
                f"{SOURCE}--{user.pk}",
                user.last_name,
                user.first_name,
                user.email,
                user.phone,
                user.last_login,
                user.get_identity_provider_display(),
                user.get_kind_display(),
                self.run_at,
            ]

        columns = {
            "source": "text",
            "id_source": "text",
            "id_unique": "text",
            "nom": "text",
            "prénom": "text",
            "email": "text",
            "téléphone": "text",
            "dernière_connexion": "timestamp with time zone",
            "auth": "text",
            "type": "text",
            "mise_à_jour": "timestamp with time zone",
        }

        populate_table(USER_TABLE, columns, serializer, [queryset])

    def populate_memberships(self):
        employers_qs = CompanyMembership.objects.select_related("company").only("company__uid", "user_id", "is_admin")
        prescribers_qs = PrescriberMembership.objects.select_related("organization").only(
            "organization__uid", "user_id", "is_admin"
        )

        def serializer(membership):
            if isinstance(membership, CompanyMembership):
                uniq_id = f"{SOURCE}--{membership.company.uid}"
            else:
                uniq_id = f"{SOURCE}--{membership.organization.uid}"

            return [
                SOURCE,
                f"{SOURCE}--{membership.user_id}",
                uniq_id,
                "administrateur" if membership.is_admin else "collaborateur",
                self.run_at,
            ]

        columns = {
            "source": "text",
            "user_id_unique": "text",
            "structure_id_unique": "text",
            "role": "text",
            "mise_à_jour": "timestamp with time zone",
        }

        populate_table(MEMBERSHIPS_TABLE, columns, serializer, [employers_qs, prescribers_qs])

    def populate_structures(self):
        prescribers_qs = PrescriberOrganization.objects.select_related("insee_city")
        company_qs = Company.objects.select_related("insee_city")

        def serializer(org):
            if isinstance(org, Company):
                org_name = org.display_name
                org_kind = f"company--{org.kind}"
            else:
                org_name = org.name
                org_kind = f"prescriber--{org.kind}"

            return [
                SOURCE,
                str(org.pk),
                f"{SOURCE}--{org.uid}",
                org.siret,
                org_name,
                org_kind,
                org.insee_city.code_insee if org.insee_city else None,
                org.address_on_one_line,
                org.post_code,
                org.latitude,
                org.longitude,
                org.email,
                org.phone,
                self.run_at,
            ]

        columns = {
            "source": "text",
            "id_source": "text",
            "id_unique": "text",
            "siret": "text",
            "nom": "text",
            "type": "text",
            "code_insee": "text",
            "adresse": "text",
            "code_postal": "text",
            "latitude": "double precision",
            "longitude": "double precision",
            "email": "text",
            "téléphone": "text",
            "mise_à_jour": "timestamp with time zone",
        }

        populate_table(STRUCTURES_TABLE, columns, serializer, querysets=[prescribers_qs, company_qs])

    def add_arguments(self, parser):
        parser.add_argument("--reset-tables", action="store_true", help="Reset the table schema")

    @tenacity.retry(
        retry=tenacity.retry_if_not_exception_type(RuntimeError),
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_fixed(5),
        after=log_retry_attempt,
    )
    def handle(self, *args, reset_tables=False, **kwargs):
        if reset_tables:
            create_table(reset=True)
        else:
            self.run_at = timezone.now()
            self.populate_users()
            self.populate_memberships()
            self.populate_structures()
