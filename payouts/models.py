import uuid
from django.db import models
from django.db.models import Sum, Q, F
from django.utils import timezone
import hashlib

class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def available_balance_paise(self):
        """Calculate available balance: credits - debits - held"""
        credits = MerchantLedger.objects.filter(
            merchant=self,
            entry_type='credit'
        ).aggregate(total=Sum('amount_paise'))['total'] or 0
        
        debits = MerchantLedger.objects.filter(
            merchant=self,
            entry_type='debit'
        ).aggregate(total=Sum('amount_paise'))['total'] or 0
        
        held = Payout.objects.filter(
            merchant=self,
            status__in=['pending', 'processing']
        ).aggregate(total=Sum('amount_paise'))['total'] or 0
        
        return credits - debits - held
    
    @property
    def held_balance_paise(self):
        """Calculate held balance from pending/processing payouts"""
        return Payout.objects.filter(
            merchant=self,
            status__in=['pending', 'processing']
        ).aggregate(total=Sum('amount_paise'))['total'] or 0
    
    @property
    def total_balance_paise(self):
        return self.available_balance_paise + self.held_balance_paise


class MerchantLedger(models.Model):
    ENTRY_TYPE_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='ledger_entries')
    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPE_CHOICES)
    amount_paise = models.BigIntegerField()
    description = models.CharField(max_length=255)
    related_payout = models.ForeignKey('Payout', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.merchant.name} - {self.entry_type} ₹{self.amount_paise/100:.2f}"


class BankAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='bank_accounts')
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.account_holder_name} - {self.account_number[-4:]}"


class IdempotencyKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE)
    key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = ('merchant', 'key')
        indexes = [
            models.Index(fields=['merchant', 'key', 'expires_at']),
        ]

    def is_expired(self):
        return timezone.now() > self.expires_at


class Payout(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='payouts')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT)
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant', 'status']),
            models.Index(fields=['status', 'last_attempted_at']),
        ]

    def __str__(self):
        return f"Payout {self.id} - {self.merchant.name} - ₹{self.amount_paise/100:.2f}"

    def can_transition_to(self, new_status):
        """Validate state machine transitions"""
        valid_transitions = {
            'pending': ['processing'],
            'processing': ['completed', 'failed'],
            'completed': [],
            'failed': [],
        }
        return new_status in valid_transitions.get(self.status, [])
