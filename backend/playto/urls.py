from django.contrib import admin
from django.urls import path, include
from payout.views import home
from payout.views import create_admin
from payout.views import create_admin

urlpatterns = [
    path('', home),
    path("create-admin/", create_admin),
    path("admin/", admin.site.urls),
    path("api/v1/", include("payout.urls")),
]
