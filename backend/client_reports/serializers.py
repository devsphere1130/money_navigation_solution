import re

from rest_framework import serializers

from .models import Client


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = [
            'id', 'title', 'full_name', 'plan_name', 'mobile', 'email',
            'net_worth', 'monthly_surplus', 'family_members', 'advisor_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'net_worth', 'monthly_surplus', 'family_members',
                            'advisor_name', 'created_at', 'updated_at']
        extra_kwargs = {'plan_name': {'required': False, 'allow_blank': True}}

    def validate_full_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError('Enter the client full name.')
        return value

    def validate_mobile(self, value):
        digits = re.sub(r'\D', '', value)
        if digits and len(digits) != 10:
            raise serializers.ValidationError('Enter a valid 10-digit mobile number.')
        return digits

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        if not attrs.get('plan_name', '').strip():
            surname = attrs['full_name'].split()[-1]
            attrs['plan_name'] = f'{surname.title()} Family Financial Plan'
        return attrs
