from django.urls import path

from .views import FundCompareView, FundDetailView, FundFundamentalsView, FundOverlapView, FundSearchView

urlpatterns = [
    path('search', FundSearchView.as_view(), name='fund-search'),
    path('funds/<str:scheme_code>', FundDetailView.as_view(), name='fund-detail'),
    path('compare', FundCompareView.as_view(), name='fund-compare'),
    path('fundamentals', FundFundamentalsView.as_view(), name='fund-fundamentals'),
    path('overlap', FundOverlapView.as_view(), name='fund-overlap'),
]
