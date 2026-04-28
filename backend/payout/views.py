"""
API Views for the Playto Payout Engine.

Critical design decisions:
1. All balance checks + payout creation happen inside a single transaction.atomic()
   with select_for_update() on the Merchant row. This serialises concurrent
   requests at the database level — no race condition possible.

2. Idempotency key is saved inside the same transaction as the payout creation,
   so either both exist or neither does (crash-safe).

3. The unique_together constraint on (merchant, key) is a second safety net
   against any duplicate insertion that might slip through.
"""

import uuid
import logging
from datetime import timedelta

from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse

from .models import Merchant, BankAccount, LedgerEntry, PayoutRequest, IdempotencyKey
from .serializers import (
    BankAccountSerializer,
    LedgerEntrySerializer,
    MerchantDashboardSerializer,
    MerchantSerializer,
    PayoutRequestSerializer,
)
from .tasks import process_payout

logger = logging.getLogger(__name__)


class MerchantListView(APIView):
    def get(self, request):
        merchants = Merchant.objects.all()
        return Response(MerchantSerializer(merchants, many=True).data)


class MerchantDashboardView(APIView):
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=404)

        ledger_entries = LedgerEntry.objects.filter(merchant=merchant).select_related("payout")[:30]
        payouts = PayoutRequest.objects.filter(merchant=merchant).select_related("bank_account")[:30]
        bank_accounts = BankAccount.objects.filter(merchant=merchant, is_active=True)

        return Response(
            {
                "merchant": MerchantDashboardSerializer(merchant).data,
                "ledger_entries": LedgerEntrySerializer(ledger_entries, many=True).data,
                "payouts": PayoutRequestSerializer(payouts, many=True).data,
                "bank_accounts": BankAccountSerializer(bank_accounts, many=True).data,
            }
        )


class CreatePayoutView(APIView):
    def post(self, request):
        # ── 1. Validate Idempotency-Key header ──────────────────────────────
        raw_key = request.headers.get("Idempotency-Key", "").strip()
        if not raw_key:
            return Response(
                {"error": "Idempotency-Key header is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            idempotency_key = uuid.UUID(raw_key)
        except ValueError:
            return Response(
                {"error": "Idempotency-Key must be a valid UUID v4"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 2. Validate request body ─────────────────────────────────────────
        merchant_id = request.data.get("merchant_id")
        amount_paise = request.data.get("amount_paise")
        bank_account_id = request.data.get("bank_account_id")

        if not all([merchant_id, amount_paise is not None, bank_account_id]):
            return Response(
                {"error": "merchant_id, amount_paise, and bank_account_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(amount_paise, int) or amount_paise <= 0:
            return Response(
                {"error": "amount_paise must be a positive integer (paise)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=status.HTTP_404_NOT_FOUND)

        # ── 3. Check for existing idempotency key ────────────────────────────
        now = timezone.now()
        existing = (
            IdempotencyKey.objects.filter(
                merchant=merchant,
                key=idempotency_key,
                expires_at__gt=now,
                response_status__gt=0,  # only return fully-committed responses
            )
            .first()
        )
        if existing:
            logger.info("Idempotency hit: merchant=%s key=%s", merchant_id, idempotency_key)
            return Response(existing.response_body, status=existing.response_status)

        # ── 4. Acquire lock + check balance + create payout atomically ───────
        try:
            with transaction.atomic():
                # Lock the merchant row for the duration of this transaction.
                # Any other concurrent payout request for the same merchant
                # will block here until we commit or rollback.
                merchant_locked = Merchant.objects.select_for_update().get(id=merchant_id)

                # Bank account must belong to this merchant
                try:
                    bank_account = BankAccount.objects.get(
                        id=bank_account_id,
                        merchant=merchant_locked,
                        is_active=True,
                    )
                except BankAccount.DoesNotExist:
                    return Response(
                        {"error": "Bank account not found or inactive"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Balance calculation happens at the DB level (SUM in SQL).
                available = merchant_locked.get_balance_paise()

                if available < amount_paise:
                    resp_body = {
                        "error": "Insufficient balance",
                        "available_paise": available,
                        "requested_paise": amount_paise,
                    }
                    resp_status = status.HTTP_422_UNPROCESSABLE_ENTITY
                    # Persist the failure response so retries get the same answer.
                    IdempotencyKey.objects.get_or_create(
                        merchant=merchant_locked,
                        key=idempotency_key,
                        defaults={
                            "response_body": resp_body,
                            "response_status": resp_status,
                            "expires_at": now + timedelta(hours=24),
                        },
                    )
                    return Response(resp_body, status=resp_status)

                # Create the payout record
                payout = PayoutRequest.objects.create(
                    merchant=merchant_locked,
                    bank_account=bank_account,
                    amount_paise=amount_paise,
                    idempotency_key=idempotency_key,
                    status=PayoutRequest.PENDING,
                )

                # Immediately debit the merchant's ledger (holds the funds).
                # On failure, tasks.py creates a matching CREDIT to return them.
                LedgerEntry.objects.create(
                    merchant=merchant_locked,
                    amount_paise=amount_paise,
                    entry_type=LedgerEntry.DEBIT,
                    payout=payout,
                    description=f"Payout #{payout.id} — funds held",
                )

                resp_body = PayoutRequestSerializer(payout).data
                resp_status = status.HTTP_201_CREATED

                # Save idempotency key in the SAME transaction.
                # If this transaction rolls back, the key is also gone — safe.
                IdempotencyKey.objects.create(
                    merchant=merchant_locked,
                    key=idempotency_key,
                    response_body=resp_body,
                    response_status=resp_status,
                    expires_at=now + timedelta(hours=24),
                )

        except IntegrityError:
            # Race: another concurrent request with the same idempotency key
            # committed first and inserted the unique IdempotencyKey row.
            # Fetch that committed response and return it.
            try:
                committed = IdempotencyKey.objects.get(
                    merchant=merchant,
                    key=idempotency_key,
                )
                return Response(committed.response_body, status=committed.response_status)
            except IdempotencyKey.DoesNotExist:
                return Response(
                    {"error": "Concurrent request conflict. Please retry."},
                    status=status.HTTP_409_CONFLICT,
                )

        # ── 5. Dispatch background processing AFTER transaction commits ──────
        process_payout.delay(payout.id)

        return Response(resp_body, status=resp_status)


class PayoutDetailView(APIView):
    def get(self, request, payout_id):
        try:
            payout = PayoutRequest.objects.select_related("bank_account", "merchant").get(
                id=payout_id
            )
        except PayoutRequest.DoesNotExist:
            return Response({"error": "Payout not found"}, status=404)
        return Response(PayoutRequestSerializer(payout).data)
    from django.http import HttpResponse

def home(request):
    return HttpResponse("Playto Backend is running")
