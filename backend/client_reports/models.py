from django.conf import settings
from django.db import models


class Client(models.Model):
    class Title(models.TextChoices):
        MR = 'Mr', 'Mr.'
        MRS = 'Mrs', 'Mrs.'
        MS = 'Ms', 'Ms.'
        DR = 'Dr', 'Dr.'

    advisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='clients')
    title = models.CharField(max_length=3, choices=Title.choices, default=Title.MR)
    full_name = models.CharField(max_length=150)
    plan_name = models.CharField(max_length=200)
    mobile = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    net_worth = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    monthly_surplus = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    family_members = models.PositiveIntegerField(default=0)
    advisor_name = models.CharField(max_length=150, default='Money Navigating Solutions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.plan_name
