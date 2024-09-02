import argparse
import csv
import datetime

from itou.approvals.models import Approval
from itou.users.enums import UserKind
from itou.utils.command import BaseCommand


def search(data, queries, *, step=0):
    if len(queries) <= step:
        return step, Approval.objects.none()
    if queries[step] <= set(data.keys()):
        approvals = Approval.objects.select_related("user__jobseeker_profile").filter(
            **{field: data[field] for field in queries[step]},
            user__kind=UserKind.JOB_SEEKER,
        )
        if approvals:
            return step, approvals
    return search(data, queries, step=step + 1)


class Command(BaseCommand):
    CSV_SEPARATOR = ";"
    QUERIES = [
        {
            "number",
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate",
            "user__jobseeker_profile__birth_place__code",
        },
        {
            "number",
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate__year",
            "user__jobseeker_profile__birth_place__code",
        },
        {
            "number",
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate",
        },
        {
            "number",
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate__year",
        },
        {
            "number",
            "user__first_name__icontains",
            "user__last_name__icontains",
        },
        {
            "number",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate",
        },
        {
            "number",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate__year",
            "user__jobseeker_profile__birth_place__code",
        },
        {
            "number",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate__year",
        },
        {
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate",
            "user__jobseeker_profile__birth_place__code",
        },
        {
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate__year",
            "user__jobseeker_profile__birth_place__code",
        },
        {
            "user__first_name__icontains",
            "user__last_name__icontains",
            "user__jobseeker_profile__birthdate",
        },
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=argparse.FileType(mode="r", encoding="ISO-8859-15"),
            help="CSV file from the ASP",
        )

    def handle(self, file, **options):
        results_file = file.name.replace(".csv", "_filled.csv")
        results = []

        for row in csv.DictReader(file, delimiter=self.CSV_SEPARATOR):
            birthdate = datetime.date(*reversed([int(part) for part in row["pph_date_naissance"].split("/")]))
            data = {
                "user__first_name__icontains": row["pph_prenom"],
                "user__last_name__icontains": row["pph_nom_usage"],
                "user__jobseeker_profile__birthdate": birthdate.isoformat(),
                "user__jobseeker_profile__birthdate__year": birthdate.year,
                "user__jobseeker_profile__birth_place__code": row["code_com_insee"],
            }
            if row["agr_numero_agrement"] != "0":
                data["number"] = row["agr_numero_agrement"]
            if row["code_com_insee"] != "[NULL]":
                data["user__jobseeker_profile__birth_place__code"] = row["code_com_insee"]

            step, approvals = search(data, self.QUERIES)
            if not approvals:
                data["user__first_name__icontains"] = row["pph_nom_usage"]
                data["user__last_name__icontains"] = row["pph_prenom"]
                step, approvals = search(data, self.QUERIES)
                step *= -1

            row["emplois_recherche_qualite"] = f"{step}"
            match len(approvals):
                case 0:
                    self.stderr.write(f"Nothing found: {step=} {data}")
                case 1:
                    self.stderr.write(f"Found something: {step=} {data}")
                    approval = approvals.get()
                    row["emplois_pass"] = approval.number
                    row["emplois_pass_date_debut"] = approval.start_at.isoformat()
                    row["emplois_pass_date_fin"] = approval.end_at.isoformat()
                    row["emplois_id_itou"] = approval.user.jobseeker_profile.asp_uid
                case _:  # > 1
                    self.stderr.write(f"Too much matches: {step=} {data}")
            results.append(row)

        with open(results_file, mode="w", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=[
                    "#",
                    "pmo_siret",
                    "rme_code_mesure_disp",
                    "pph_id",
                    "pph_nom_usage",
                    "pph_prenom",
                    "pph_date_naissance",
                    "code_com_insee",
                    "lib_com",
                    "agr_numero_agrement",
                    "emplois_pass",
                    "emplois_pass_date_debut",
                    "emplois_pass_date_fin",
                    "emplois_id_itou",
                    "emplois_recherche_qualite",
                ],
                delimiter=self.CSV_SEPARATOR,
            )
            writer.writeheader()
            writer.writerows(results)
        self.stderr.write(f"Result in: {results_file}")
