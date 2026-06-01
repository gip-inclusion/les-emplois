from django.conf import settings
from django.urls import path

from itou.utils.enums import ItouEnvironment
from itou.www.components import views


app_name = "components"

urlpatterns = []

if settings.ITOU_ENVIRONMENT != ItouEnvironment.PROD:
    urlpatterns.append(path("", views.show_components, name="index"))
    urlpatterns.append(path("demo_buttons_form", views.demo_buttons_form, name="demo_buttons_form"))
