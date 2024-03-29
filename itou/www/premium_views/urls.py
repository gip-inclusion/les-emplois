from django.urls import path

from itou.www.premium_views.views import RefreshSyncJobApplicationView, SaveNoteView, SyncJobApplicationListView


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "premium_views"

urlpatterns = [
    path("note/<int:synced_job_application_id>/", SaveNoteView.as_view(), name="save_note"),
    path("job_applications/", SyncJobApplicationListView.as_view(), name="job_applications"),
    path("job_applications/refresh/", RefreshSyncJobApplicationView.as_view(), name="refresh"),
]
