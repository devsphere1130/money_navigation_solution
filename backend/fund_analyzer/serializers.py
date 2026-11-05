from rest_framework import serializers


class SourceSerializer(serializers.Serializer):
    source = serializers.CharField()
    asOfDate = serializers.CharField(allow_null=True, required=False)


class FundSearchResultSerializer(SourceSerializer):
    scheme_code = serializers.CharField()
    scheme_name = serializers.CharField()
    amc = serializers.CharField(allow_null=True, required=False)
    category = serializers.CharField(allow_null=True, required=False)
    scheme_type = serializers.CharField(allow_null=True, required=False)
    plan = serializers.CharField(allow_null=True, required=False)
    option = serializers.CharField(allow_null=True, required=False)
    isin = serializers.CharField(allow_null=True, required=False)
    nav = serializers.FloatField(allow_null=True, required=False)


class FundSearchResponseSerializer(SourceSerializer):
    results = FundSearchResultSerializer(many=True)


class MetricSetSerializer(serializers.Serializer):
    r1m = serializers.FloatField(allow_null=True, required=False)
    r3m = serializers.FloatField(allow_null=True, required=False)
    r6m = serializers.FloatField(allow_null=True, required=False)
    r1y = serializers.FloatField(allow_null=True, required=False)
    r3y = serializers.FloatField(allow_null=True, required=False)
    r5y = serializers.FloatField(allow_null=True, required=False)
    volatility = serializers.FloatField(allow_null=True, required=False)
    sharpe = serializers.FloatField(allow_null=True, required=False)
    maxDrawdown = serializers.FloatField(allow_null=True, required=False)
    rollingReturns = serializers.ListField(required=False)
    calendarYearReturns = serializers.ListField(required=False)
    growthOf10000 = serializers.ListField(required=False)
    sip = serializers.DictField(allow_null=True, required=False)


class FundDetailSerializer(SourceSerializer):
    scheme_code = serializers.CharField()
    scheme_name = serializers.CharField()
    amc = serializers.CharField(allow_null=True, required=False)
    category = serializers.CharField(allow_null=True, required=False)
    scheme_type = serializers.CharField(allow_null=True, required=False)
    plan = serializers.CharField(allow_null=True, required=False)
    option = serializers.CharField(allow_null=True, required=False)
    isin = serializers.CharField(allow_null=True, required=False)
    nav = serializers.FloatField(allow_null=True, required=False)
    nav_date = serializers.CharField(allow_null=True, required=False)
    ter = serializers.FloatField(allow_null=True, required=False)
    ter_as_of = serializers.CharField(allow_null=True, required=False)
    aum = serializers.FloatField(allow_null=True, required=False)
    aum_unit = serializers.CharField(allow_null=True, required=False)
    aum_as_of = serializers.CharField(allow_null=True, required=False)
    holdings = serializers.ListField(child=serializers.DictField(), required=False)
    holdings_as_of = serializers.CharField(allow_null=True, required=False)
    benchmark = serializers.CharField(allow_null=True, required=False)
    allocation = serializers.DictField(allow_null=True, required=False)
    sectors = serializers.ListField(child=serializers.DictField(), required=False)
    riskometer = serializers.DictField(allow_null=True, required=False)
    metrics = MetricSetSerializer(allow_null=True, required=False)


class CompareRequestSerializer(serializers.Serializer):
    scheme_codes = serializers.ListField(child=serializers.CharField(), min_length=1, max_length=8)
    risk_free_rate = serializers.FloatField(allow_null=True, required=False, min_value=0, max_value=1)

    def validate_scheme_codes(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError('scheme_codes must contain unique scheme codes.')
        return value


class CompareResponseSerializer(SourceSerializer):
    funds = FundDetailSerializer(many=True)
    correlation = serializers.DictField()
    summary = serializers.DictField()
