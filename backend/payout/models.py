import uuid
from django.db import models
from django.db.models import BigIntegerField, Sum, Case, When, F
from django.core.exceptions import ValidationError


class Merchant(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_balance_paise(self):
        """
        Balance calculated entirely at the database level using a single
        aggregation query. Credits add; debits subtract.
        No Python arithmetic on fetched rows — this is intentional.
        """
        result = self.ledger_entries.aggregate(
            balance=Sum(
                Case(
                    When(entry_type=LedgerEntry.CREDIT, then=F("amount_paise")),
                    When(entry_type=LedgerEntry.DEBIT, then=-F("amount_paise")),
                    output_field=BigIntegerField(),
                )
            )
        )
        return result["balance"] or 0

    def get_held_paise(self):
        """Sum of pending/processing payout amounts (display only)."""
        result = self.payout_requests.filter(
            status__in=[PayoutRequest.PENDING, PayoutRequest.PROCESSING]
        ).aggregate(held=Sum("amount_paise"))
        return result["held"] or 0


class BankAccount(models.Model):
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="bank_accounts"
    )
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account_holder_name} ···{self.account_number[-4:]}"


class LedgerEntry(models.Model):
    CREDIT = "credit"
    DEBIT = "debit"
    TYPE_CHOICES = [(CREDIT, "Credit"), (DEBIT, "Debit")]

    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    # Always a positive integer in paise. The entry_type determines sign.
    amount_paise = models.BigIntegerField()
    entry_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    description = models.TextField()
    payout = models.ForeignKey(
        "PayoutRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.entry_type.upper()} ₹{self.amount_paise / 100:.2f} — {self.merchant}"


class PayoutRequest(models.Model):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PROCESSING, "Processing"),
        (COMPLETED, "Completed"),
        (FAILED, "Failed"),
    ]

    # State machine: only these forward transitions are legal.
    VALID_TRANSITIONS = {
        PENDING: [PROCESSING],
        PROCESSING: [COMPLETED, FAILED],
        COMPLETED: [],  # terminal
        FAILED: [],  # terminal
    }

    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="payout_requests"
    )
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    amount_paise = models.BigIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    idempotency_key = models.UUIDField()
    attempt_count = models.IntegerField(default=0)
    failure_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def transition_to(self, new_status: str) -> None:
        """
        Enforce the state machine. Raises ValueError on any illegal transition.
        This is where failed→completed and completed→anything are blocked.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Illegal state transition: {self.status} → {new_status}. "
                f"Allowed from '{self.status}': {allowed or 'none (terminal state)'}"
            )
        self.status = new_status

    def __str__(self):
        return f"Payout #{self.id} [{self.status}] ₹{self.amount_paise / 100:.2f}"


class IdempotencyKey(models.Model):
    """
    Stores processed request keys per merchant.
    The unique_together constraint + select_for_update on the merchant row
    makes it impossible to create two payouts for the same key.
    Keys expire after 24 hours per spec.
    """

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE)
    key = models.UUIDField()
    response_body = models.JSONField(default=dict)
    response_status = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = [("merchant", "key")]
        indexes = [
            models.Index(fields=["merchant", "key"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"IdempotencyKey {self.key} for {self.merchant}"
    from django.db import models

class LedgerEntry(models.Model):
    ENTRY_TYPES = (
        ('credit', 'Credit'),
        ('debit', 'Debit'),
        ('hold', 'Hold'),
        ('release', 'Release'),
    )

    merchant = models.ForeignKey('Merchant', on_delete=models.CASCADE)
    amount_paise = models.BigIntegerField()
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.merchant.name} - {self.entry_type} - {self.amount_paise}"
