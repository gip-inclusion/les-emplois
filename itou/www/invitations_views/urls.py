from django.urls import path

from itou.www.invitations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "invitations_views"

urlpatterns = [path("accept/<str:encoded_invitation_id>", views.accept, name="accept")]
