from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from itou.www.home.views import home
from itou.www.signup import views as signup_views
from itou.www.dashboard import views as dashboard_views

urlpatterns = [

    path('admin/', admin.site.urls),

    # --------------------------------------------------------------------------------------
    # Override allauth `account_signup` URL.
    # /accounts/signup/                                 account_signup
    # We don't want any user to be able to signup using the default allauth `signup` url
    # because we have multiple specific signup processes for different kind of users.
    re_path(
        r"^accounts/signup/$", TemplateView.as_view(template_name="signup/signup.html")
    ),
    # Override allauth `account_change_password` URL.
    # /accounts/password/change/                        account_change_password
    # https://github.com/pennersr/django-allauth/issues/468
    re_path(r"^accounts/password/change/$", dashboard_views.password_change),
    # --------------------------------------------------------------------------------------
    # Other allauth URLs.
    path('accounts/', include('allauth.urls')),
    # --------------------------------------------------------------------------------------

    path('city/', include('itou.cities.urls')),
    path('jobs/', include('itou.jobs.urls')),

    # www.
    path('', home, name='home'),
    path('signup/', include('itou.www.signup.urls')),
    path('dashboard/', include('itou.www.dashboard.urls')),
    path('siae/', include('itou.www.siaes_views.urls')),
    path('apply/', include('itou.www.apply.urls')),

    # Errors pages.
    path('403/', TemplateView.as_view(template_name='403.html'), name='403'),
    path('404/', TemplateView.as_view(template_name='404.html'), name='404'),
    path('500/', TemplateView.as_view(template_name='500.html'), name='500'),

]

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
