"""Guided journeys of the "Prochaines étapes" experiment.

A journey prepares an action in a side drawer: the facts it rests on, the steps, the options the existing form will
offer (their real labels), then hands over to that form. The forms themselves are not rewritten: they keep their
validation and permissions. Without JavaScript, the action button leads straight to the form.

Every sentence here states what the platform does; nothing that the code does not do.
"""

import dataclasses

from itou.approvals.enums import ProlongationRequestDenyProposedAction, ProlongationRequestDenyReason
from itou.approvals.models import Suspension
from itou.companies.enums import ProSupportReportBarrier, ProSupportReportOrientation, ProSupportReportSolution
from itou.job_applications.enums import RefusalReason
from itou.rdv_insertion.enums import ParticipationStatus


NBSP = " "
PASS_IAE = f"PASS{NBSP}IAE"


@dataclasses.dataclass
class OptionList:
    title: str
    options: list


@dataclasses.dataclass
class Journey:
    title: str
    # (label, value) pairs.
    facts: list
    steps: list
    continue_label: str
    option_lists: list = dataclasses.field(default_factory=list)
    note: str | None = None


def _fr(date):
    return f"{date:%d/%m/%Y}"


def job_application(job_application, sender):
    company = job_application.to_company
    facts = [("Reçue le", _fr(job_application.created_at))]
    if sender:
        facts.append(("Envoyée par", sender.display_name))
    return Journey(
        title="Répondre à la candidature",
        facts=facts,
        steps=[
            "Lire la candidature et les informations de la personne.",
            f"Répondre{NBSP}: mettre la candidature à l’étude, en attente, accepter l’embauche ou la décliner.",
        ],
        option_lists=[
            OptionList(
                title=f"Motifs proposés si vous déclinez{NBSP}:",
                options=[label for value, label in RefusalReason.displayed_choices(company.kind) if value],
            )
        ],
        continue_label="Ouvrir la candidature",
    )


def approval_suspension(approval, company, contract_end_date):
    return Journey(
        title=f"Suspendre le {PASS_IAE}",
        facts=[
            ("Contrat terminé le", _fr(contract_end_date)),
            (PASS_IAE, approval.number_with_spaces),
            ("Fin prévue", _fr(approval.end_at)),
            ("Reliquat", approval.get_remainder_display()),
        ],
        steps=[
            "Choisir le motif et les dates de la suspension.",
            f"Valider{NBSP}: la date de fin du {PASS_IAE} est repoussée d’autant.",
        ],
        option_lists=[
            OptionList(
                title=f"Motifs de suspension{NBSP}:",
                options=[label for _value, label in Suspension.Reason.displayed_choices_for_siae(company)],
            )
        ],
        note=f"Seule la structure qui a embauché la personne en dernier peut suspendre son {PASS_IAE}.",
        continue_label=f"Suspendre le {PASS_IAE}",
    )


def pro_support_report_fill(contract_end_date, ended):
    return Journey(
        title="Remplir le bilan d’accompagnement",
        facts=[("Contrat terminé le" if ended else "Fin du contrat", _fr(contract_end_date))],
        steps=[
            "Indiquer les freins périphériques encore présents.",
            "Situer l’autonomie de la personne dans sa recherche d’emploi, de 1 à 5.",
            "Indiquer la solution envisagée après le contrat ou, à défaut, l’orientation la plus adaptée.",
        ],
        option_lists=[
            OptionList(title=f"Freins proposés{NBSP}:", options=ProSupportReportBarrier.labels),
            OptionList(title=f"Solutions proposées{NBSP}:", options=ProSupportReportSolution.labels),
            OptionList(title=f"Orientations proposées{NBSP}:", options=ProSupportReportOrientation.labels),
        ],
        note=(
            "Le bilan est transmis au dernier prescripteur habilité qui a accompagné la personne. "
            "Une fois envoyé, il ne peut plus être modifié."
        ),
        continue_label="Remplir le bilan",
    )


def pro_support_report_request(contract_end_date, ended):
    return Journey(
        title="Demander le bilan d’accompagnement",
        facts=[("Contrat terminé le" if ended else "Fin du contrat", _fr(contract_end_date))],
        steps=[
            "Ouvrir la fiche de la personne.",
            (
                f"Cliquer sur «{NBSP}Demander un bilan d’accompagnement{NBSP}»{NBSP}: "
                "un e-mail pré-rempli s’ouvre, adressé à la structure d’insertion."
            ),
        ],
        note=(
            "C’est la structure d’insertion qui remplit le bilan. Une fois rempli, il apparaît ici, "
            f"dans «{NBSP}Lire le bilan d’accompagnement{NBSP}»."
        ),
        continue_label="Ouvrir la fiche",
    )


def prolongation_request(prolongation_request):
    facts = [("Demandée le", _fr(prolongation_request.created_at))]
    if prolongation_request.declared_by_siae:
        facts.append(("Par", prolongation_request.declared_by_siae.display_name))
    facts += [
        ("Motif", prolongation_request.get_reason_display()),
        (
            "Prolongation demandée",
            f"du {_fr(prolongation_request.start_at)} au {_fr(prolongation_request.end_at)}",
        ),
        (f"Fin actuelle du {PASS_IAE}", _fr(prolongation_request.approval.end_at)),
    ]
    return Journey(
        title="Traiter la demande de prolongation",
        facts=facts,
        steps=[
            "Lire la demande et, le cas échéant, le justificatif joint.",
            "Accepter ou refuser la demande.",
        ],
        option_lists=[
            OptionList(title=f"Motifs de refus{NBSP}:", options=ProlongationRequestDenyReason.labels),
            OptionList(
                title=f"Actions à proposer en cas de refus{NBSP}:",
                options=ProlongationRequestDenyProposedAction.labels,
            ),
        ],
        continue_label="Ouvrir la demande",
    )


def eligibility(job_application):
    return Journey(
        title="Valider l’éligibilité IAE",
        facts=[
            ("Candidature du", _fr(job_application.created_at)),
            ("Chez", job_application.to_company.display_name),
        ],
        steps=[
            "Réaliser un diagnostic socio-professionnel lors d’un entretien individuel.",
            "Sélectionner les critères administratifs d’éligibilité correspondants.",
        ],
        continue_label="Valider l’éligibilité",
    )


def appointment(appointment):
    return Journey(
        title="Préciser le statut du rendez-vous",
        facts=[("Rendez-vous du", _fr(appointment.start_at)), ("Motif", appointment.reason)],
        steps=[
            "Ouvrir le rendez-vous pour retrouver ses informations.",
            "Renseigner son statut dans RDV-Insertion, d’où il remonte sur la plateforme.",
        ],
        option_lists=[
            OptionList(
                title=f"Statuts possibles{NBSP}:",
                options=[status.label for status in ParticipationStatus if status != ParticipationStatus.UNKNOWN],
            )
        ],
        continue_label="Voir le rendez-vous",
    )
