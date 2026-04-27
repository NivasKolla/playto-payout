from django.contrib import admin
from .models import Merchant, BankAccount, LedgerEntry, PayoutRequest, IdempotencyKey


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "email", "get_balance_display", "created_at"]
    readonly_fields = ["created_at"]

    def get_balance_display(self, obj):
        return f"₹{obj.get_balance_paise() / 100:.2f}"
    get_balance_display.short_description = "Balance"


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "account_holder_name", "ifsc_code", "is_active"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "entry_type", "amount_paise", "description", "created_at"]
    list_filter = ["entry_type", "merchant"]


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "amount_paise", "status", "attempt_count", "created_at"]
    list_filter = ["status", "merchant"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ["key", "merchant", "response_status", "created_at", "expires_at"]
