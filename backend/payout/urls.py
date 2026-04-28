from django.urls import path
from .views import (
    MerchantListView,
    MerchantDashboardView,
    CreatePayoutView,
    BankAccountListView,
    PayoutDetailView,
)

urlpatterns = [
    path("merchants/", MerchantListView.as_view(), name="merchant-list"),
    path("merchants/<int:merchant_id>/", MerchantDashboardView.as_view(), name="merchant-dashboard"),
    path("payouts/", CreatePayoutView.as_view(), name="create-payout"),
    path("bank-accounts/", BankAccountListView.as_view()),
    path("payouts/<int:payout_id>/", PayoutDetailView.as_view(), name="payout-detail"),
]
