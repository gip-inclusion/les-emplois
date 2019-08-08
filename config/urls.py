from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views import defaults as default_views
from django.views.generic import TemplateView

from itou.home.views import home

urlpatterns = [

    path('admin/', admin.site.urls),

    # Allauth signup URL is overridden in `itou.accounts.urls`.
    # So order is important: the first match listed will have priority.
    path('accounts/', include('itou.accounts.urls')),
    path('accounts/', include('allauth.urls')),

    path('', home, name='home'),
    path('city/', include('itou.cities.urls')),
    path('siae/', include('itou.siae.urls')),

]

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
