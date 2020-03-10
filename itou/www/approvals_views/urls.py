from django.urls import path

from itou.www.approvals_views import views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "approvals"

urlpatterns = [
    path(
        "download/<uuid:job_application_id>",
        views.approval_as_pdf,
        name="approval_as_pdf",
    )
]
