import json

import factory

from itou.eligibility import models
from itou.users.factories import JobSeekerFactory, PrescriberFactory
from itou.eligibility.forms.form_v_1_0_0 import EligibilityForm


class EligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object for unit tests."""

    class Meta:
        model = models.EligibilityDiagnosis

    job_seeker = factory.SubFactory(JobSeekerFactory)
    author = factory.SubFactory(PrescriberFactory)
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER
    form_version = EligibilityForm.VERSION
    form_cleaned_data = json.dumps(
        {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_2": [
                "senior_50_ans",
                "travailleur_handicape",
                "primo_arrivant",
            ],
        }
    )
    data = json.dumps(
        {
            "Besoins d'accompagnement": [
                [
                    "Faire face à des difficultés administratives ou juridiques",
                    ["Prendre en compte une problématique judiciaire"],
                ]
            ],
            "Critères administratifs": [
                [
                    "Critères administratifs de niveau 2",
                    ["Senior (+50 ans)", "Travailleur handicapé", "Primo arrivant"],
                ]
            ],
        }
    )
