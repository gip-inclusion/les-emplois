from django.urls import path

from itou.www.siae_evaluations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siae_evaluations_views"

urlpatterns = [
    # vincentporte, note for victorperron
    # ajout ID - impacts vue et reverse de la vue (simple, peu critique), template dashboard
    path("samples_selection", views.samples_selection, name="samples_selection"),
    path(
        "institution_evaluated_siae_list/<int:evaluation_campaign_pk>/",
        views.institution_evaluated_siae_list,
        name="institution_evaluated_siae_list",
    ),
    path(
        "institution_evaluated_siae_detail/<int:evaluated_siae_pk>/",
        views.institution_evaluated_siae_detail,
        name="institution_evaluated_siae_detail",
    ),
    path(
        "institution_evaluated_job_application/<int:evaluated_job_application_pk>/",
        views.institution_evaluated_job_application,
        name="institution_evaluated_job_application",
    ),
    path(
        "institution_evaluated_administrative_criteria/<int:evaluated_administrative_criteria_pk>/<slug:action>",
        views.institution_evaluated_administrative_criteria,
        name="institution_evaluated_administrative_criteria",
    ),
    path(
        "institution_evaluated_siae_validation/<int:evaluated_siae_pk>/",
        views.institution_evaluated_siae_validation,
        name="institution_evaluated_siae_validation",
    ),
    # vincentporte, note for victorperron
    # ajout ID - impacts vue et reverse de la vue , méthode `get_email_to_siae_selected`, template dashboard
    # simple, source de confusion si la SIAE est selectionnée dans deux campagnes actives en meme temps,
    # notamment pour le calcul de l'état `is_submittable`
    path("siae_job_applications_list", views.siae_job_applications_list, name="siae_job_applications_list"),
    path(
        "siae_select_criteria/<int:evaluated_job_application_pk>/",
        views.siae_select_criteria,
        name="siae_select_criteria",
    ),
    path(
        "siae_upload_doc/<int:evaluated_administrative_criteria_pk>/",
        views.siae_upload_doc,
        name="siae_upload_doc",
    ),
    # vincentporte, note for victorperron
    # ajout ID - impacts vue et reverse de la vue , template `siae_job_applications_list`
    # simple, critique si la SIAE est selectionnée dans deux campagnes actives en meme temps,
    # car la vue tente de soumettre toutes les autoprescriptions possibles
    # risque de fonctionnements mal explicables
    path("siae_submit_proofs", views.siae_submit_proofs, name="siae_submit_proofs"),
]
