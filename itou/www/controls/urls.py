from django.urls import path

from itou.www.controls import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "controls"

urlpatterns = [
    path("review_self_approvals", views.review_self_approvals, name="review_self_approvals"),
    path("self_approvals_list", views.self_approvals_list, name="self_approvals_list"),
    path("self_approvals/<int:approval_id>", views.self_approvals, name="self_approvals"),
]
