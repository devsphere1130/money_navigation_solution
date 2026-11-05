from django.urls import path

from .views import FundCompareView, FundDetailView, FundFundamentalsView, FundOverlapImportView, FundOverlapView, FundSearchView, PortfolioCoverageView

urlpatterns = [
    path('search', FundSearchView.as_view(), name='fund-search'),
    path('funds/<str:scheme_code>', FundDetailView.as_view(), name='fund-detail'),
    path('compare', FundCompareView.as_view(), name='fund-compare'),
    path('fundamentals', FundFundamentalsView.as_view(), name='fund-fundamentals'),
    path('overlap', FundOverlapView.as_view(), name='fund-overlap'),
    path('overlap/import', FundOverlapImportView.as_view(), name='fund-overlap-import'),
    path('overlap/coverage', PortfolioCoverageView.as_view(), name='fund-overlap-coverage'),
]
