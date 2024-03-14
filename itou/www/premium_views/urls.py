from django.urls import path

from itou.www.premium_views.views import SaveNoteView


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "premium_views"

urlpatterns = [
    path("note/<uuid:job_application_id>/", SaveNoteView.as_view(), name="save_note"),
]
