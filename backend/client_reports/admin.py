from django.contrib import admin

from .models import (
    AssetItem, Client, ClientProfile, ExpenseItem, FamilyMember, IncomeItem, InsuranceCover,
    InvestmentItem, LiabilityItem,
)

admin.site.register([
    Client, ClientProfile, IncomeItem, ExpenseItem, InvestmentItem, AssetItem, LiabilityItem,
    InsuranceCover, FamilyMember,
])
