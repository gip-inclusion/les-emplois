from django import template
from django.conf import settings
from django.template.defaulttags import CsrfTokenNode
from django.template.loader import get_template
from django.urls import reverse
from django.utils.html import format_html

from itou.nexus.enums import Service
from itou.users.enums import UserKind
from itou.utils.enums import ItouEnvironment
from itou.utils.templatetags.matomo import matomo_event
from itou.utils.templatetags.url_add_query import autologin_proconnect


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
            "etoile": "nexus/nx-forme-etoile-emplois.png",
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
            "etoile": "nexus/nx-forme-etoile-dora.png",
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
            "etoile": "nexus/nx-forme-etoile-marche.png",
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
            "etoile": "nexus/nx-forme-etoile-monrecap.png",
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
            "etoile": "nexus/nx-forme-etoile-pilotage.png",
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


def get_services_context():
    return {
        Service.EMPLOIS: {
            "name": "Les Emplois de l’inclusion",
            "logo": "logo-emploi-inclusion.svg",
            "one_click_activation": False,
        },
        Service.DORA: {
            "name": "DORA",
            "logo": "logo-dora.svg",
            "one_click_activation": False,
        },
        Service.MARCHE: {
            "name": "Le marché de l’inclusion",
            "logo": "logo-marche-inclusion.svg",
            "one_click_activation": False,
        },
        Service.MON_RECAP: {
            "name": "Mon Récap",
            "logo": "logo-monrecap.svg",
            "one_click_activation": False,
        },
        Service.PILOTAGE: {
            "name": "Le Pilotage de l’inclusion",
            "logo": "logo-pilotage-inclusion.svg",
            "one_click_activation": True,
        },
    }


def get_service_urls(user):
    dora_url = "https://dora.inclusion.gouv.fr/"
    marche_url = "https://lemarche.inclusion.gouv.fr/"
    if settings.ITOU_ENVIRONMENT not in [ItouEnvironment.PROD, ItouEnvironment.TEST]:
        dora_url = "https://staging.dora.inclusion.gouv.fr/"
        marche_url = "https://staging.lemarche.inclusion.beta.gouv.fr/"

    return {
        Service.EMPLOIS: {
            "activated": reverse("dashboard:index"),
            "activable": reverse("dashboard:index"),
        },
        Service.DORA: {
            "activated": autologin_proconnect(dora_url, user),
            "activable": autologin_proconnect(dora_url, user),
        },
        Service.MARCHE: {
            "activated": f"{marche_url}accounts/login/",
            "activable": f"{marche_url}accounts/signup/",
        },
        Service.MON_RECAP: {
            "activated": "https://mon-recap.inclusion.beta.gouv.fr/formulaire-commande-carnets/",
            "activable": reverse("nexus:mon_recap"),
        },
        Service.PILOTAGE: {
            "activated": reverse("dashboard:index_stats"),
            "activable": reverse("dashboard:index_stats"),
        },
    }


@register.simple_tag(takes_context=True)
def nexus_dropdown(context):
    dropdown_status = context["request"].nexus_dropdown
    if dropdown_status.get("mvp_enabled"):
        if dropdown_status["proconnect"] is False:
            template = get_template("nexus/components/dropdown_no_proconnect.html")
            proconnect_params = {
                # we don't care which kind is chosen since the user already exists so the kind won't be updated
                "user_kind": UserKind.PRESCRIBER,
                "previous_url": context["request"].get_full_path(),
                "next_url": reverse("nexus:homepage"),
            }
            pro_connect_url = (
                reverse("pro_connect:authorize", query=proconnect_params) if settings.PRO_CONNECT_BASE_URL else None
            )
            template_context = {
                "pro_connect_url": pro_connect_url,
                "matomo_account_type": "non défini",
                "SHOW_DEMO_ACCOUNTS_BANNER": settings.SHOW_DEMO_ACCOUNTS_BANNER,
            }
            return template.render(template_context)
        template = get_template("nexus/components/dropdown.html")
        # Prepare context
        services_context = get_services_context()
        service_urls = get_service_urls(context["user"])
        activated_services, activable_services = [], []
        for service in Service.activable():
            if service in dropdown_status["activated_services"]:
                activated_services.append(
                    {"service": service, **services_context[service], "url": service_urls[service]["activated"]}
                )
            else:
                activable_services.append(
                    {"service": service, **services_context[service], "url": service_urls[service]["activable"]}
                )

        template_context = {
            "user_name": f"{context['user'].first_name} {context['user'].last_name[0]}",
            "user": context["user"],
            "activated_services": activated_services,
            "activable_services": activable_services,
        }
        return template.render(template_context)
    return ""
