import csv
from urllib.parse import urlencode

import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from itou.inclusion_pass import catalogue, connecteurs, services
from itou.inclusion_pass.models import Accompagnement, BilanIntervention, Offreur
from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.insertion.opening_hours import format_osm_hours
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.urls import get_safe_url
from itou.www.inclusion_pass_views.forms import BilanInterventionForm, DemandesRecuesFilterForm
from itou.www.insertion_views.forms import RefusalOrientationForm
from itou.www.job_seekers_views.views import get_assignments_for_display


SESSION_ACCUEIL_KEY = "inclusion_pass_accueil"
DEMO_PERSONA_EMAIL = connecteurs.PERSONA_EMAIL


def _personne_or_404(request):
    if not request.user.is_authenticated or request.user.kind != UserKind.JOB_SEEKER:
        raise Http404
    return request.user


def _is_offreur(request):
    return request.from_offreur


# Person side


@login_not_required
@readonly_view
def accueil(request, uuid_accueil):
    """Landing page of the reception QR code, shared by every person visiting the offreur."""
    offreur = get_object_or_404(Offreur, uuid_accueil=uuid_accueil)
    request.session[SESSION_ACCUEIL_KEY] = str(offreur.uuid_accueil)
    if request.user.is_authenticated and request.user.kind == UserKind.JOB_SEEKER:
        return redirect("inclusion_pass:consentement", uuid_accueil=offreur.uuid_accueil)
    return render(
        request,
        "inclusion_pass/accueil.html",
        {"offreur": offreur, "connexion_demo": settings.DEBUG},
    )


@login_not_required
@http_methods(db_write=["POST"])
def connexion_demo(request):
    if not settings.DEBUG:
        raise Http404
    user = get_object_or_404(User, email=DEMO_PERSONA_EMAIL)
    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
    if uuid_accueil := request.session.get(SESSION_ACCUEIL_KEY):
        return redirect("inclusion_pass:consentement", uuid_accueil=uuid_accueil)
    return redirect("inclusion_pass:mon_pass")


@http_methods(db_readonly=["GET"], db_write=["POST"])
def consentement(request, uuid_accueil):
    personne = _personne_or_404(request)
    offreur = get_object_or_404(Offreur, uuid_accueil=uuid_accueil)
    if request.method == "POST":
        services.accorder(personne, offreur, request.POST.getlist("donnees"))
        request.session.pop(SESSION_ACCUEIL_KEY, None)
        return redirect(f"{reverse('inclusion_pass:mon_pass')}?confirmation={offreur.uid}")
    blocs = [
        {**bloc, "donnees": [{"cle": cle, **donnee, "source": catalogue.source(cle)} for cle, donnee in donnees]}
        for _, bloc, donnees in catalogue.par_bloc(offreur.donnees_demandees)
    ]
    autorisations = [{"cle": cle, **info} for cle, info in catalogue.AUTORISATIONS.items()]
    return render(
        request,
        "inclusion_pass/consentement.html",
        {"offreur": offreur, "blocs": blocs, "autorisations": autorisations},
    )


@http_methods(db_readonly=["GET"], db_write=["POST"])
def mon_pass(request):
    personne = _personne_or_404(request)
    if request.method == "POST":
        offreur = get_object_or_404(Offreur, uid=request.POST["offreur"])
        donnee = request.POST.get("donnee") or None
        services.retirer(personne, offreur, donnee)
        if donnee:
            messages.success(request, f"{catalogue.libelle(donnee)} : accès retiré pour {offreur.display_name}.")
        else:
            messages.success(request, f"{offreur.display_name} n’a plus accès à vos informations.")
        return redirect("inclusion_pass:mon_pass")
    consentements = personne.pass_consentements.actifs().select_related("offreur").order_by("offreur", "granted_at")
    par_offreur = {}
    for consentement in consentements:
        par_offreur.setdefault(consentement.offreur, []).append(consentement)
    confirmation = Offreur.objects.filter(uid=request.GET.get("confirmation")).first()
    return render(
        request,
        "inclusion_pass/mon_pass.html",
        {
            "par_offreur": par_offreur,
            "journal": personne.pass_acces.select_related("offreur")[:50],
            "confirmation": confirmation,
        },
    )


# Offreur side: an authenticated member of an Offreur organization


def vue_ensemble(request):
    """Home of the offreur: new people arrived through the QR code and orientations to process."""
    offreur = request.current_organization
    orientations = _orientations_recues(offreur).filter(status=OrientationStatus.PENDING)
    return render(
        request,
        "inclusion_pass/offreur/vue_ensemble.html",
        {
            "nouveaux": _nouveaux_usagers(offreur),
            "orientations_a_traiter": orientations[:5],
            "orientations_a_traiter_nombre": orientations.count(),
            "bilan": services.bilan_impact(offreur),
        },
    )


def _nouveaux_usagers(offreur):
    return offreur.accompagnements.filter(vu_par_offreur=False).select_related("personne", "orientation")


@readonly_view
@check_request(_is_offreur)
def nouveaux_usagers(request):
    return render(
        request,
        "inclusion_pass/offreur/_nouveaux_usagers.html",
        {"nouveaux": _nouveaux_usagers(request.current_organization)},
    )


def pilotage(request):
    """Impact dashboard of the offreur, with charts."""
    bilan = services.bilan_impact(request.current_organization)
    graphiques = [
        {"id": f"graphique-{cle}", "titre": titre, "type": "doughnut", "series": bilan["repartitions"][cle]}
        for cle, titre in [
            ("qpv", "Part des résidents QPV"),
            ("rsa", "Part des bénéficiaires du RSA"),
            ("genre", "Répartition par genre"),
            ("age", "Répartition par âge"),
        ]
    ]
    graphiques.append(
        {
            "id": "graphique-sorties",
            "titre": "Sorties positives (emploi ou formation)",
            "type": "bar",
            "unite": "%",
            "series": [
                {"libelle": f"À {mois} mois", "nombre": sortie["taux"] or 0}
                for mois, sortie in bilan["sorties"].items()
            ],
        }
    )
    return render(
        request,
        "inclusion_pass/offreur/pilotage.html",
        {"bilan": bilan, "graphiques": graphiques, "modeles_export": services.MODELES_EXPORT},
    )


@readonly_view
@check_request(_is_offreur)
def pilotage_csv(request):
    modele = request.GET.get("modele", "complet")
    if modele not in services.MODELES_EXPORT:
        raise Http404
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="bilan-impact-{modele}.csv"'
    csv.writer(response, delimiter=";").writerows(services.lignes_export(request.current_organization, modele))
    return response


def _orientations_recues(offreur):
    return (
        Orientation.objects.filter(service__structure=offreur.structure)
        .order_by("-created_at", "-pk")
        .select_related("beneficiary", "sender", "sender_prescriber_organization", "sender_company", "service")
    )


@readonly_view
@check_request(_is_offreur)
def demandes_recues(request):
    orientations = _orientations_recues(request.current_organization)
    filters_form = DemandesRecuesFilterForm(orientations, request.GET, request)
    filters_counter = 0
    if filters_form.is_valid():
        orientations = filters_form.filter(orientations)
        filters_counter = filters_form.get_qs_filters_counter()
    context = {
        "orientations_page": pager(orientations, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_DEFAULT),
        "filters_form": filters_form,
        "filters_counter": filters_counter,
        "accompagnements": {
            accompagnement.personne_id: accompagnement
            for accompagnement in request.current_organization.accompagnements.filter(ended_at=None)
        },
    }
    template = "inclusion_pass/offreur/_demandes_recues_liste.html" if request.htmx else None
    return render(request, template or "inclusion_pass/offreur/demandes_recues.html", context)


def _orientation_recue(request, orientation_id):
    return get_object_or_404(
        _orientations_recues(request.current_organization).select_related(
            "beneficiary__jobseeker_profile", "beneficiary__jobseeker_profile__birth_country", "service__source"
        ),
        id=orientation_id,
    )


@http_methods(db_readonly=["GET"], db_write=["POST"])
@check_request(_is_offreur)
def orientation_recue(request, orientation_id):
    orientation = _orientation_recue(request, orientation_id)
    if request.method == "POST" and request.POST.get("action") == "accept":
        if orientation.accept.is_available():
            orientation.accept()
            messages.success(
                request,
                "Demande d’orientation acceptée||"
                "Un e-mail récapitulatif va vous être envoyé ainsi qu’à toutes les parties prenantes.",
                extra_tags="toast",
            )
        else:
            messages.warning(request, "Cette orientation a déjà été traitée.", extra_tags="toast")
        return HttpResponseRedirect(request.get_full_path())
    accompagnement = request.current_organization.accompagnements.filter(personne=orientation.beneficiary).first()
    return render(
        request,
        "inclusion_pass/offreur/orientation_recue.html",
        {
            "orientation": orientation,
            "accompagnement": accompagnement,
            "can_view_personal_information": True,
            # Shows the provider-side wording of the shared template, without its token-based actions
            "can_process": True,
            "has_actions": False,
            "peut_traiter": orientation.status == OrientationStatus.PENDING,
            "back_url": get_safe_url(request, "back_url", fallback_url=reverse("inclusion_pass:demandes_recues")),
            "matomo_custom_title": "Détail d’une orientation reçue",
        },
    )


@http_methods(db_readonly=["GET"], db_write=["POST"])
@check_request(_is_offreur)
def refuser_orientation(request, orientation_id):
    orientation = _orientation_recue(request, orientation_id)
    detail_url = reverse("inclusion_pass:orientation_recue", args=[orientation.id])
    if orientation.status != OrientationStatus.PENDING:
        return HttpResponseRedirect(detail_url)
    form = RefusalOrientationForm(instance=orientation, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        orientation = form.save(commit=False)
        orientation.refuse()
        messages.info(
            request,
            "Demande d’orientation déclinée||"
            "Un e-mail récapitulatif va vous être envoyé ainsi qu’à toutes les parties prenantes.",
            extra_tags="toast",
        )
        return HttpResponseRedirect(detail_url)
    return render(
        request,
        "insertion/orientations/refuse.html",
        {"orientation": orientation, "form": form, "reset_url": detail_url, "matomo_custom_title": "Décliner"},
    )


@readonly_view
@check_request(_is_offreur)
def usagers(request):
    termines = request.GET.get("statut") == "termines"
    accompagnements = request.current_organization.accompagnements.filter(ended_at__isnull=not termines)
    return render(
        request,
        "inclusion_pass/offreur/usagers.html",
        {
            "accompagnements_page": pager(
                accompagnements.select_related("personne", "orientation"),
                request.GET.get("page"),
                items_per_page=settings.PAGE_SIZE_DEFAULT,
            ),
            "termines": termines,
            "nombre_en_cours": request.current_organization.accompagnements.filter(ended_at=None).count(),
            "nombre_termines": request.current_organization.accompagnements.exclude(ended_at=None).count(),
        },
    )


def _accompagnement(request, accompagnement_id):
    return get_object_or_404(
        Accompagnement.objects.select_related(
            "personne", "orientation__sender_prescriber_organization", "prescripteur"
        ),
        offreur=request.current_organization,
        pk=accompagnement_id,
    )


@http_methods(db_write=["GET", "POST"])
@check_request(_is_offreur)
def fiche(request, accompagnement_id):
    accompagnement = _accompagnement(request, accompagnement_id)
    if request.method == "POST":
        services.recuperer(accompagnement.personne, request.current_organization)
        messages.success(request, "Informations actualisées depuis les sources.", extra_tags="toast")
        return redirect("inclusion_pass:fiche", accompagnement_id=accompagnement.pk)
    if not accompagnement.vu_par_offreur:
        accompagnement.vu_par_offreur = True
        accompagnement.save(update_fields=["vu_par_offreur"])
    blocs = services.donnees_pour_offreur(request.current_organization, accompagnement.personne)
    return render(
        request,
        "inclusion_pass/offreur/fiche.html",
        {
            "accompagnement": accompagnement,
            "blocs": [bloc for bloc in blocs if bloc["cle"] != "pieces"],
            "pieces": next((bloc for bloc in blocs if bloc["cle"] == "pieces"), None),
            "back_url": get_safe_url(request, "back_url", fallback_url=reverse("inclusion_pass:usagers")),
            "matomo_custom_title": "Fiche usager pour offreur de service",
        },
    )


@readonly_view
@check_request(_is_offreur)
def accompagnateurs(request, accompagnement_id):
    accompagnement = _accompagnement(request, accompagnement_id)
    active_assignments, ended_assignments = get_assignments_for_display(accompagnement.personne)
    return render(
        request,
        "inclusion_pass/offreur/accompagnateurs.html",
        {
            "accompagnement": accompagnement,
            "active_assignments": active_assignments,
            "ended_assignments": ended_assignments,
            "back_url": get_safe_url(request, "back_url", fallback_url=reverse("inclusion_pass:usagers")),
            "matomo_custom_title": "Accompagnateurs d’un usager pour offreur de service",
        },
    )


@http_methods(db_readonly=["GET"], db_write=["POST"])
@check_request(_is_offreur)
def bilan_intervention(request, accompagnement_id):
    accompagnement = _accompagnement(request, accompagnement_id)
    suivi_autorise = catalogue.SUIVI_LONG in services.cles_consenties(
        accompagnement.personne, request.current_organization
    )
    if request.method == "POST" and suivi_autorise:
        services.simuler_suivi(accompagnement)
        return redirect("inclusion_pass:bilan_intervention", accompagnement_id=accompagnement.pk)
    back_url = get_safe_url(request, "back_url", fallback_url=reverse("inclusion_pass:usagers"))
    return render(
        request,
        "inclusion_pass/offreur/bilan_intervention.html",
        {
            "accompagnement": accompagnement,
            "bilan": BilanIntervention.objects.filter(accompagnement=accompagnement).select_related("auteur").first(),
            "situations": accompagnement.situations.all(),
            "suivi_autorise": suivi_autorise,
            "back_url": back_url,
            "matomo_custom_title": "Bilan de l’intervention pour offreur de service",
        },
    )


@http_methods(db_readonly=["GET"], db_write=["POST"])
@check_request(_is_offreur)
def remplir_bilan(request, accompagnement_id):
    """Form of the report of the follow-up, in the format of the SIAE pro support report."""
    accompagnement = _accompagnement(request, accompagnement_id)
    if BilanIntervention.objects.filter(accompagnement=accompagnement).exists():
        raise Http404
    back_url = get_safe_url(request, "back_url", fallback_url=reverse("inclusion_pass:usagers"))
    bilan_url = (
        reverse("inclusion_pass:bilan_intervention", args=[accompagnement.pk])
        + "?"
        + urlencode({"back_url": back_url})
    )
    form = BilanInterventionForm(
        request.path,
        data=request.POST or None,
        initial={"has_solution": request.GET.get("has_solution")},
        instance=BilanIntervention(accompagnement=accompagnement, auteur=request.user),
    )
    if request.method == "POST" and form.is_valid():
        services.envoyer_bilan(form.instance)
        messages.success(request, "Bilan de l’intervention envoyé", extra_tags="toast")
        return HttpResponseRedirect(bilan_url)
    return render(
        request,
        "inclusion_pass/offreur/bilan_intervention_form.html",
        {
            "form": form,
            "accompagnement": accompagnement,
            "back_url": back_url,
            "reset_url": bilan_url,
            "matomo_custom_title": "Remplir le bilan de l’intervention",
        },
    )


@readonly_view
@check_request(_is_offreur)
def presentation(request):
    structure = request.current_organization.structure
    return render(
        request,
        "inclusion_pass/offreur/presentation.html",
        {
            "structure": structure,
            "reseaux_porteurs": structure.reseaux_porteurs.all(),
            "formatted_opening_hours": format_osm_hours(structure.opening_hours),
        },
    )


@readonly_view
@check_request(_is_offreur)
def offres(request):
    services_qs = request.current_organization.structure.services.prefetch_related("thematics").order_by("name")
    orientations = list(_orientations_recues(request.current_organization))
    for service in services_qs:
        service.orientations_nombre = sum(o.service_id == service.pk for o in orientations)
        service.orientations_a_traiter = sum(
            o.service_id == service.pk and o.status == OrientationStatus.PENDING for o in orientations
        )
    return render(request, "inclusion_pass/offreur/offres.html", {"services": services_qs})


@readonly_view
@check_request(_is_offreur)
def qr_code_accueil(request):
    offreur = request.current_organization
    lien = request.build_absolute_uri(reverse("inclusion_pass:accueil", args=[offreur.uuid_accueil]))
    qr_code = segno.make(lien).svg_inline(scale=8, title=f"QR code d’accueil de {offreur.display_name}")
    return render(request, "inclusion_pass/offreur/qr_code_accueil.html", {"lien": lien, "qr_code": qr_code})
