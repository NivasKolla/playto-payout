from rest_framework import serializers
from .models import Merchant, BankAccount, LedgerEntry, PayoutRequest


class BankAccountSerializer(serializers.ModelSerializer):
    masked_account = serializers.SerializerMethodField()

    class Meta:
        model = BankAccount
        fields = ["id", "account_holder_name", "ifsc_code", "masked_account", "is_active"]

    def get_masked_account(self, obj):
        return f"···{obj.account_number[-4:]}"


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ["id", "amount_paise", "entry_type", "description", "payout_id", "created_at"]


class PayoutRequestSerializer(serializers.ModelSerializer):
    bank_account = BankAccountSerializer(read_only=True)

    class Meta:
        model = PayoutRequest
        fields = [
            "id",
            "amount_paise",
            "status",
            "idempotency_key",
            "bank_account",
            "attempt_count",
            "failure_reason",
            "created_at",
            "updated_at",
            "processing_started_at",
        ]


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "created_at"]


class MerchantDashboardSerializer(serializers.ModelSerializer):
    balance_paise = serializers.SerializerMethodField()
    held_paise = serializers.SerializerMethodField()
    available_paise = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = ["id", "name", "email", "balance_paise", "held_paise", "available_paise"]

    def get_balance_paise(self, obj):
        return obj.get_balance_paise()

    def get_held_paise(self, obj):
        return obj.get_held_paise()

    def get_available_paise(self, obj):
        # Balance already reflects debits from held payouts
        return obj.get_balance_paise()
