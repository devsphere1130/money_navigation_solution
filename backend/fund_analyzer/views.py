from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .providers import ProviderError
from .serializers import CompareRequestSerializer, CompareResponseSerializer, FundDetailSerializer, FundSearchResponseSerializer, FundSearchResultSerializer
from .services import compare_funds, fetch_fund_data, search_funds


class FundSearchView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        query = str(request.query_params.get('q', '')).strip()
        if len(query) < 2:
            return Response({'source': 'AMFI', 'asOfDate': None, 'results': []})
        try:
            payload = search_funds(query)
            payload['results'] = [FundSearchResultSerializer({'source': payload['source'], 'asOfDate': payload['asOfDate'], **row}).data for row in payload['results']]
            return Response(FundSearchResponseSerializer(payload).data)
        except ProviderError as exc:
            return Response({'detail': str(exc), 'source': 'AMFI', 'asOfDate': None}, status=503)


class FundDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, scheme_code: str):
        try:
            payload = fetch_fund_data(scheme_code, include_history=False)
            return Response(FundDetailSerializer(payload).data)
        except ProviderError as exc:
            return Response({'detail': str(exc), 'source': 'MFAPI (backup)', 'asOfDate': None}, status=503)


class FundCompareView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        request_serializer = CompareRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response({'detail': request_serializer.errors, 'source': 'AMFI', 'asOfDate': None}, status=400)
        try:
            validated = request_serializer.validated_data
            risk_free_rate = validated.get('risk_free_rate')
            payload = compare_funds(validated['scheme_codes'], risk_free_rate if risk_free_rate is not None else settings.FUND_ANALYZER_RISK_FREE_RATE)
            return Response(CompareResponseSerializer(payload).data)
        except ProviderError as exc:
            return Response({'detail': str(exc), 'source': 'MFAPI (backup)', 'asOfDate': None}, status=503)
