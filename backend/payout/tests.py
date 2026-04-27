"""
Tests for the Playto Payout Engine.

Two categories that the spec explicitly requires:
  1. Concurrency — two simultaneous 60-rupee requests against 100-rupee balance
  2. Idempotency — same key twice returns identical response, one payout

We use threads to simulate true concurrency and psycopg2 advisory locks via
select_for_update to prove that only one request wins the race.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import BankAccount, LedgerEntry, Merchant, PayoutRequest, IdempotencyKey


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_merchant(name="Test Merchant", email=None):
    return Merchant.objects.create(
        name=name,
        email=email or f"{uuid.uuid4().hex[:8]}@test.com",
    )


def make_bank_account(merchant):
    return BankAccount.objects.create(
        merchant=merchant,
        account_number="12345678901234",
        ifsc_code="HDFC0001234",
        account_holder_name=merchant.name,
    )


def credit(merchant, amount_paise, description="Seeded credit"):
    return LedgerEntry.objects.create(
        merchant=merchant,
        amount_paise=amount_paise,
        entry_type=LedgerEntry.CREDIT,
        description=description,
    )


# ---------------------------------------------------------------------------
# 1. Concurrency test
# ---------------------------------------------------------------------------


class ConcurrencyTest(TransactionTestCase):
    """
    Use TransactionTestCase (not TestCase) so that each thread runs against
    real committed data — TestCase wraps everything in one transaction, which
    would make select_for_update invisible to other threads.
    """

    def test_concurrent_overdraft_prevented(self):
        """
        A merchant with 100 rupees (10,000 paise) submits two simultaneous
        60-rupee (6,000 paise) payout requests. Exactly one must succeed;
        the other must be rejected with an insufficient-balance error.
        """
        merchant = make_merchant("Concurrent Merchant")
        bank_account = make_bank_account(merchant)
        credit(merchant, 10_000)  # ₹100

        results = []
        errors = []

        def request_payout():
            from django.test import RequestFactory
            from rest_framework.test import APIClient

            client = APIClient()
            payload = {
                "merchant_id": merchant.id,
                "amount_paise": 6_000,
                "bank_account_id": bank_account.id,
            }
            response = client.post(
                "/api/v1/payouts/",
                data=payload,
                format="json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),  # different key per thread
            )
            results.append(response.status_code)

        threads = [threading.Thread(target=request_payout) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = results.count(201)
        rejections = results.count(422)

        self.assertEqual(successes, 1, f"Expected exactly 1 success, got: {results}")
        self.assertEqual(rejections, 1, f"Expected exactly 1 rejection, got: {results}")

        # Verify balance invariant: credits - debits == balance
        balance = merchant.get_balance_paise()
        payouts_created = PayoutRequest.objects.filter(merchant=merchant).count()
        self.assertEqual(payouts_created, 1)

        # Balance should be 10,000 - 6,000 = 4,000
        self.assertEqual(balance, 4_000)

    def test_balance_invariant_after_concurrent_payouts(self):
        """
        Five concurrent 1,000-paise requests against 3,000 paise balance.
        Exactly 3 should succeed, 2 should be rejected. Balance ends at 0.
        """
        merchant = make_merchant("Balance Invariant Merchant")
        bank_account = make_bank_account(merchant)
        credit(merchant, 3_000)

        results = []

        def request_payout():
            from rest_framework.test import APIClient

            client = APIClient()
            response = client.post(
                "/api/v1/payouts/",
                data={
                    "merchant_id": merchant.id,
                    "amount_paise": 1_000,
                    "bank_account_id": bank_account.id,
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
            results.append(response.status_code)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(request_payout) for _ in range(5)]
            for f in as_completed(futures):
                f.result()

        successes = results.count(201)
        self.assertEqual(successes, 3, f"Expected 3 successes out of 5, got: {results}")

        # Invariant: balance must equal 0 (all 3,000 paise held)
        self.assertEqual(merchant.get_balance_paise(), 0)


# ---------------------------------------------------------------------------
# 2. Idempotency test
# ---------------------------------------------------------------------------


class IdempotencyTest(TestCase):
    def setUp(self):
        self.merchant = make_merchant("Idempotency Merchant")
        self.bank_account = make_bank_account(self.merchant)
        credit(self.merchant, 50_000)  # ₹500

    def _post_payout(self, idempotency_key, amount_paise=5_000):
        from rest_framework.test import APIClient

        client = APIClient()
        return client.post(
            "/api/v1/payouts/",
            data={
                "merchant_id": self.merchant.id,
                "amount_paise": amount_paise,
                "bank_account_id": self.bank_account.id,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(idempotency_key),
        )

    def test_same_key_returns_same_response(self):
        """Second call with same idempotency key must return the exact same response."""
        key = uuid.uuid4()

        r1 = self._post_payout(key)
        r2 = self._post_payout(key)

        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.data["id"], r2.data["id"])

    def test_no_duplicate_payout_created(self):
        """Same key must never create two payout records."""
        key = uuid.uuid4()
        initial_count = PayoutRequest.objects.filter(merchant=self.merchant).count()

        self._post_payout(key)
        self._post_payout(key)
        self._post_payout(key)  # triple call for good measure

        final_count = PayoutRequest.objects.filter(merchant=self.merchant).count()
        self.assertEqual(final_count, initial_count + 1)

    def test_different_keys_create_separate_payouts(self):
        """Different idempotency keys must each create their own payout."""
        initial_count = PayoutRequest.objects.filter(merchant=self.merchant).count()

        for _ in range(3):
            r = self._post_payout(uuid.uuid4())
            self.assertEqual(r.status_code, 201)

        self.assertEqual(
            PayoutRequest.objects.filter(merchant=self.merchant).count(),
            initial_count + 3,
        )

    def test_idempotency_key_scoped_per_merchant(self):
        """Same UUID key used by different merchants must create independent payouts."""
        merchant2 = make_merchant("Second Merchant")
        bank2 = make_bank_account(merchant2)
        credit(merchant2, 50_000)

        shared_key = uuid.uuid4()

        from rest_framework.test import APIClient

        client = APIClient()

        r1 = client.post(
            "/api/v1/payouts/",
            data={
                "merchant_id": self.merchant.id,
                "amount_paise": 5_000,
                "bank_account_id": self.bank_account.id,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(shared_key),
        )
        r2 = client.post(
            "/api/v1/payouts/",
            data={
                "merchant_id": merchant2.id,
                "amount_paise": 5_000,
                "bank_account_id": bank2.id,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(shared_key),
        )

        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertNotEqual(r1.data["id"], r2.data["id"])


# ---------------------------------------------------------------------------
# 3. State machine test
# ---------------------------------------------------------------------------


class StateMachineTest(TestCase):
    def setUp(self):
        self.merchant = make_merchant("SM Merchant")
        self.bank_account = make_bank_account(self.merchant)
        credit(self.merchant, 50_000)

    def _make_payout(self, status=PayoutRequest.PENDING):
        return PayoutRequest.objects.create(
            merchant=self.merchant,
            bank_account=self.bank_account,
            amount_paise=1_000,
            idempotency_key=uuid.uuid4(),
            status=status,
        )

    def test_illegal_transitions_raise(self):
        illegal = [
            (PayoutRequest.COMPLETED, PayoutRequest.PENDING),
            (PayoutRequest.COMPLETED, PayoutRequest.PROCESSING),
            (PayoutRequest.COMPLETED, PayoutRequest.FAILED),
            (PayoutRequest.FAILED, PayoutRequest.COMPLETED),
            (PayoutRequest.FAILED, PayoutRequest.PENDING),
            (PayoutRequest.FAILED, PayoutRequest.PROCESSING),
            (PayoutRequest.PROCESSING, PayoutRequest.PENDING),
        ]
        for from_status, to_status in illegal:
            payout = self._make_payout(status=from_status)
            with self.assertRaises(ValueError, msg=f"{from_status} → {to_status} should raise"):
                payout.transition_to(to_status)

    def test_legal_transitions_succeed(self):
        payout = self._make_payout()
        payout.transition_to(PayoutRequest.PROCESSING)
        payout.transition_to(PayoutRequest.COMPLETED)

        payout2 = self._make_payout()
        payout2.transition_to(PayoutRequest.PROCESSING)
        payout2.transition_to(PayoutRequest.FAILED)


# ---------------------------------------------------------------------------
# 4. Balance invariant test
# ---------------------------------------------------------------------------


class BalanceInvariantTest(TestCase):
    def test_balance_equals_credits_minus_debits(self):
        """The core ledger invariant: balance == SUM(credits) - SUM(debits)."""
        merchant = make_merchant("Invariant Merchant")
        credit(merchant, 100_000)
        credit(merchant, 50_000)
        LedgerEntry.objects.create(
            merchant=merchant,
            amount_paise=30_000,
            entry_type=LedgerEntry.DEBIT,
            description="Test debit",
        )

        expected = 100_000 + 50_000 - 30_000  # 120,000 paise
        self.assertEqual(merchant.get_balance_paise(), expected)
