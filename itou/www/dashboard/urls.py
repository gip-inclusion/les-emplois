from django.urls import path

from itou.www.dashboard import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("token_api", views.api_token, name="api_token"),
    path("edit_user_email", views.edit_user_email, name="edit_user_email"),
    path("edit_user_info", views.edit_user_info, name="edit_user_info"),
    path("edit_user_notifications", views.edit_user_notifications, name="edit_user_notifications"),
    path("edit_job_seeker_info/<uuid:job_seeker_public_id>", views.edit_job_seeker_info, name="edit_job_seeker_info"),
    path("switch-organization", views.switch_organization, name="switch_organization"),
    path(
        "activate_ic_account",
        views.AccountMigrationView.as_view(),
        name="activate_ic_account",
    ),
]

# NOTE: temporary URL patterns to help with migration which will be removed next week
urlpatterns += [
    path(
        "edit_job_seeker_info/<int:job_seeker_public_id>",
        views.edit_job_seeker_info,
    )
]
