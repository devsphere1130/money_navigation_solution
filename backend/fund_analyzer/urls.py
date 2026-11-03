from django.urls import path

from .views import FundCompareView, FundDetailView, FundSearchView

urlpatterns = [
    path('search', FundSearchView.as_view(), name='fund-search'),
    path('funds/<str:scheme_code>', FundDetailView.as_view(), name='fund-detail'),
    path('compare', FundCompareView.as_view(), name='fund-compare'),
]
