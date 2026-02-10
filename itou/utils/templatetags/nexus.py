from django import template
from django.template.defaulttags import CsrfTokenNode
from django.template.loader import get_template
from django.urls import reverse
from django.utils.html import format_html

from itou.nexus.enums import Service
from itou.utils.templatetags.matomo import matomo_event


register = template.Library()


def get_template_context(context, service):
    template_context = {
        "service": service,
        "new_service_shown": context["new_service_shown"],
    }
    services_context = {
        Service.EMPLOIS: {
            "name": "Les Emplois de l’inclusion",
            "description": "Le service de recrutement et de gestion des PASS IAE.",
            "logo": "logo-emploi-inclusion-mono.svg",
            "items_short": [
                "Publiez vos recrutements",
                "Recevez des candidatures",
                "Obtenez un PASS IAE",
            ],
            "items_long": [
                "Publiez vos fiches de poste",
                "Recevez des candidatures de la part des accompagnateurs et des candidats",
                format_html(
                    """
                    Obtenez un
                    <a href="{}" class="btn-link has-external-link" target="_blank">PASS IAE</a>
                    en ligne dès l’embauche d’un candidat",
                    """,
                    "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/14733528375185--PASS-IAE-Comment-%C3%A7a-marche",
                ),
            ],
            # TODO : when it's possible to access this page without a EMPLOIS account
            "activate_button": format_html(
                """
                <button class="btn btn-ico btn-primary" {} type="button">
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </button>
                """,
                matomo_event("nexus", "activer-service", Service.EMPLOIS),
            ),
            "responsive_buttons": format_html(
                """
                <a href="{}" class="btn btn-link has-external-link ps-0" {} target="_blank">En savoir plus</a>
                <button class="btn btn-ico btn-primary" {} type="button">
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </button>
                """,
                reverse("home:hp"),
                matomo_event("nexus", "decouvrir-service", Service.EMPLOIS),
                matomo_event("nexus", "activer-service", Service.EMPLOIS),
            ),
            "find_out_url": reverse("home:hp"),
            "id": "emplois",
        },
        Service.DORA: {
            "name": "DORA",
            "description": "Le service d’aide à la prescription pour la levée des freins périphériques à l’emploi.",
            "logo": "logo-dora-mono.svg",
            "items_short": [
                "Saisissez votre offre de service",
                "Service identifié par les pro",
                "Gérez les demandes dans votre espace",
            ],
            "items_long": [
                "Saisissez ou importez votre offre de service",
                "Service identifié par les professionnels de l’insertion grâce au moteur de recherche",
                "Gérez vos demandes de mobilisation dans un espace dédié",
            ],
            "activate_button": format_html(
                """
                <a href="{}" class="btn btn-ico btn-primary" {}>
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </a>
                """,
                context["dora_url"],
                matomo_event("nexus", "activer-service", Service.DORA),
            ),
            "responsive_buttons": format_html(
                """
                <a href="{}" class="btn btn-link has-external-link ps-0" {} target="_blank">En savoir plus</a>
                <a href="{}" class="btn btn-ico btn-primary" {}>
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </a>
                """,
                "https://dora.inclusion.gouv.fr/",
                matomo_event("nexus", "decouvrir-service", Service.DORA),
                context["dora_url"],
                matomo_event("nexus", "activer-service", Service.DORA),
            ),
            "find_out_url": "https://dora.inclusion.gouv.fr/",
            "id": "dora",
        },
        Service.MARCHE: {
            "name": "Le marché de l’inclusion",
            "description": "Le service de mise en relation entre acheteurs et structures d’insertion.",
            "logo": "logo-marche-inclusion-mono.svg",
            "items_short": [
                "Renseignez votre activité",
                "Recevez des demandes de devis",
                "Développez votre CA",
            ],
            "items_long": [
                "Renseignez votre activité commerciale",
                "Recevez des demandes de clients publics et privés",
                "Développez votre activité commerciale",
            ],
            "activate_button": format_html(
                """
                <a href="{}" class="btn btn-ico btn-primary" {}>
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </a>
                """,
                context["marche_url"],
                matomo_event("nexus", "activer-service", Service.MARCHE),
            ),
            "responsive_buttons": format_html(
                """
                <a href="{}" class="btn btn-link has-external-link ps-0" {} target="_blank">En savoir plus</a>
                <a href="{}" class="btn btn-ico btn-primary" {}>
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </a>
                """,
                "https://lemarche.inclusion.gouv.fr/",
                matomo_event("nexus", "decouvrir-service", Service.MARCHE),
                context["marche_url"],
                matomo_event("nexus", "activer-service", Service.MARCHE),
            ),
            "find_out_url": "https://lemarche.inclusion.gouv.fr/",
            "id": "marche",
        },
        Service.MON_RECAP: {
            "name": "Mon Récap",
            "description": "Le carnet papier retraçant le parcours d’insertion d’une personne.",
            "logo": "logo-monrecap-mono.svg",
            "items_short": [
                "Démarches et parcours centralisés",
                "Support accessible",
                "Commun à tous les pros",
            ],
            "items_long": [
                "Outillez vos usagers avec un support concret pour suivre leurs démarches et parcours",
                "Facilitez votre accompagnement et communiquez entre professionnels grâce à un carnet commun",
                "Choisissez un outil accessible non numérique",
            ],
            "activate_button": format_html(
                """
                <form method="post" action="{}">
                    {}
                    <button class="btn btn-ico btn-block btn-primary" {}>
                        <i class="ri-toggle-line" aria-hidden="true"></i>
                        <span>Activer ce service</span>
                    </button>
                </form>
                """,
                context["monrecap_url"],
                CsrfTokenNode().render(context),
                matomo_event("nexus", "activer-service", Service.MON_RECAP),
            ),
            "responsive_buttons": format_html(
                """
                <form method="post" action="{}">
                    <a href="{}" class="btn btn-link has-external-link ps-0" {} target="_blank">En savoir plus</a>
                    {}
                    <button class="btn btn-ico btn-primary" {}>
                        <i class="ri-toggle-line" aria-hidden="true"></i>
                        <span>Activer ce service</span>
                    </button>
                </form>
                """,
                context["monrecap_url"],
                "https://mon-recap.inclusion.beta.gouv.fr/",
                matomo_event("nexus", "decouvrir-service", Service.MON_RECAP),
                CsrfTokenNode().render(context),
                matomo_event("nexus", "activer-service", Service.MON_RECAP),
            ),
            "find_out_url": "https://mon-recap.inclusion.beta.gouv.fr/",
            "id": "monrecap",
        },
        Service.PILOTAGE: {
            "name": "Le Pilotage de l’inclusion",
            "description": "Le service présentant les données sur les politiques publiques d’insertion.",
            "logo": "logo-pilotage-inclusion-mono.svg",
            "items_short": [
                "Statistiques nationales",
                "Données sur votre organisation",
                "Aide à la décision",
            ],
            "items_long": [
                "Consultez les statistiques nationales sur l’inclusion dans l’emploi",
                "Suivez et analysez les données spécifiques à votre organisation",
                "Prenez des décisions et argumentez grâce aux données",
            ],
            "activate_button": format_html(
                """
                <a href="{}" class="btn btn-ico btn-primary" {}>
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </a>
                """,
                context["pilotage_url"],
                matomo_event("nexus", "activer-service", Service.PILOTAGE),
            ),
            "responsive_buttons": format_html(
                """
                <a href="{}" class="btn btn-link has-external-link ps-0" {} target="_blank">En savoir plus</a>
                <a href="{}" class="btn btn-ico btn-primary" {}>
                    <i class="ri-toggle-line" aria-hidden="true"></i>
                    <span>Activer ce service</span>
                </a>
                """,
                "https://pilotage.inclusion.beta.gouv.fr/",
                matomo_event("nexus", "decouvrir-service", Service.PILOTAGE),
                context["pilotage_url"],
                matomo_event("nexus", "activer-service", Service.PILOTAGE),
            ),
            "find_out_url": "https://pilotage.inclusion.beta.gouv.fr/",
            "id": "pilotage",
        },
    }
    template_context.update(services_context[service])
    return template_context


@register.simple_tag(takes_context=True)
def new_service_v1(context, service):
    template = get_template("nexus/components/new_service_v1.html")
    return template.render(get_template_context(context, service))


@register.simple_tag(takes_context=True)
def new_service_v2(context, service):
    template = get_template("nexus/components/new_service_v2.html")
    return template.render(get_template_context(context, service))


@register.simple_tag(takes_context=True)
def new_service_v2_details(context, service):
    template = get_template("nexus/components/new_service_v2_details.html")
    return template.render(get_template_context(context, service))


@register.simple_tag(takes_context=True)
def new_service_v2_responsive(context, service):
    template = get_template("nexus/components/new_service_v2_responsive.html")
    return template.render(get_template_context(context, service))
