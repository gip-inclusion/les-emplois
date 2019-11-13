from django.urls import path
from django.views.generic import TemplateView


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "content"

urlpatterns = [
    path(
        "faq/",
        TemplateView.as_view(template_name="content/faq.html"),
        name="faq",
    ),
    path(
        "faciliter_embauche_en_iae/",
        TemplateView.as_view(template_name="content/faciliter_embauche_en_iae.html"),
        name="faciliter_embauche_en_iae",
    ),
    path(
        "experimentation/",
        TemplateView.as_view(template_name="content/experimentation.html"),
        name="experimentation",
    ),
    path(
        "inclusion_kesako/",
        TemplateView.as_view(template_name="content/inclusion_kesako.html"),
        name="inclusion_kesako",
    ),
    path(
        "le_pacte_ambition_iae/",
        TemplateView.as_view(template_name="content/le_pacte_ambition_iae.html"),
        name="le_pacte_ambition_iae",
    ),
    path(
        "qui_sommes_nous/",
        TemplateView.as_view(template_name="content/qui_sommes_nous.html"),
        name="qui_sommes_nous",
    ),
    path(
        "simplifier_les_procedures/",
        TemplateView.as_view(template_name="content/simplifier_les_procedures.html"),
        name="simplifier_les_procedures",
    ),
]
