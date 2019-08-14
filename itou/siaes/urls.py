from django.urls import path, re_path

from itou.siaes import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = 'siae'

urlpatterns = [

    re_path(r'^card/(?P<siret>\d{14})$', views.card, name='card'),
    path('search', views.search, name='search'),

]
