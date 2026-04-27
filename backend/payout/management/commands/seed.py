"""
Seed script: creates 3 merchants with bank accounts and credit history.
Run with: python manage.py seed
"""

import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payout.models import BankAccount, LedgerEntry, Merchant, PayoutRequest


class Command(BaseCommand):
    help = "Seed the database with test merchants, bank accounts, and ledger entries"

    def handle(self, *args, **kwargs):
        self.stdout.write("🌱 Seeding database...")

        # ── Merchant 1: Agency with healthy balance ──────────────────────────
        m1, _ = Merchant.objects.get_or_create(
            email="priya@brightpixels.in",
            defaults={"name": "Bright Pixels Agency"},
        )
        ba1, _ = BankAccount.objects.get_or_create(
            merchant=m1,
            account_number="3071234567890",
            defaults={
                "ifsc_code": "HDFC0001200",
                "account_holder_name": "Priya Sharma",
            },
        )
        credits_m1 = [
            (5_000_000, "Client payment — Acme Corp (USD 6,000)"),
            (2_500_000, "Client payment — TechFlow Inc (USD 3,000)"),
            (1_000_000, "Client payment — GreenLeaf (USD 1,200)"),
        ]
        for amount, desc in credits_m1:
            LedgerEntry.objects.get_or_create(
                merchant=m1,
                amount_paise=amount,
                entry_type=LedgerEntry.CREDIT,
                description=desc,
            )
        # One completed payout
        p1 = PayoutRequest.objects.create(
            merchant=m1,
            bank_account=ba1,
            amount_paise=2_000_000,
            idempotency_key=uuid.uuid4(),
            status=PayoutRequest.COMPLETED,
        )
        LedgerEntry.objects.create(
            merchant=m1,
            amount_paise=2_000_000,
            entry_type=LedgerEntry.DEBIT,
            payout=p1,
            description=f"Payout #{p1.id} — completed",
        )

        # ── Merchant 2: Freelancer ───────────────────────────────────────────
        m2, _ = Merchant.objects.get_or_create(
            email="rahul@freelance.dev",
            defaults={"name": "Rahul Dev — Freelancer"},
        )
        ba2, _ = BankAccount.objects.get_or_create(
            merchant=m2,
            account_number="9087654321001",
            defaults={
                "ifsc_code": "ICIC0002345",
                "account_holder_name": "Rahul Verma",
            },
        )
        credits_m2 = [
            (800_000, "Client payment — Startup XYZ (USD 960)"),
            (1_200_000, "Client payment — DataCore LLC (USD 1,440)"),
        ]
        for amount, desc in credits_m2:
            LedgerEntry.objects.get_or_create(
                merchant=m2,
                amount_paise=amount,
                entry_type=LedgerEntry.CREDIT,
                description=desc,
            )
        # One failed payout (funds returned)
        p2 = PayoutRequest.objects.create(
            merchant=m2,
            bank_account=ba2,
            amount_paise=500_000,
            idempotency_key=uuid.uuid4(),
            status=PayoutRequest.FAILED,
            failure_reason="Bank declined the transfer",
        )
        LedgerEntry.objects.create(
            merchant=m2,
            amount_paise=500_000,
            entry_type=LedgerEntry.DEBIT,
            payout=p2,
            description=f"Payout #{p2.id} — funds held",
        )
        LedgerEntry.objects.create(
            merchant=m2,
            amount_paise=500_000,
            entry_type=LedgerEntry.CREDIT,
            payout=p2,
            description=f"Payout #{p2.id} failed — funds returned",
        )

        # ── Merchant 3: Small seller ─────────────────────────────────────────
        m3, _ = Merchant.objects.get_or_create(
            email="meena@craftseller.co",
            defaults={"name": "Meena Crafts"},
        )
        ba3, _ = BankAccount.objects.get_or_create(
            merchant=m3,
            account_number="5566778899001",
            defaults={
                "ifsc_code": "SBIN0003456",
                "account_holder_name": "Meena Patel",
            },
        )
        LedgerEntry.objects.get_or_create(
            merchant=m3,
            amount_paise=350_000,
            entry_type=LedgerEntry.CREDIT,
            description="Client payment — Etsy reseller (USD 420)",
        )

        self.stdout.write(self.style.SUCCESS("✅ Seed complete!"))
        self.stdout.write("")
        self.stdout.write(f"  Merchant 1: {m1.name} — Balance: ₹{m1.get_balance_paise()/100:.2f}")
        self.stdout.write(f"  Merchant 2: {m2.name} — Balance: ₹{m2.get_balance_paise()/100:.2f}")
        self.stdout.write(f"  Merchant 3: {m3.name} — Balance: ₹{m3.get_balance_paise()/100:.2f}")
