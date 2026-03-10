from django.conf import settings
from django.urls import path

from itou.utils.enums import ItouEnvironment
from itou.www.components import views


app_name = "components"

urlpatterns = []

if settings.ITOU_ENVIRONMENT != ItouEnvironment.PROD:
    urlpatterns.append(
        path("", views.show_components, name="index"),
    )
