"""
Payout processing tasks.

Lifecycle:
  PENDING → PROCESSING → COMPLETED  (70% of bank calls)
  PENDING → PROCESSING → FAILED     (20% of bank calls)
  PENDING → PROCESSING → [stuck]    (10% of bank calls — rescued by check_stuck_payouts)

On failure, funds are returned atomically with the state transition in a single
database transaction, so there is no window where the payout is FAILED but funds
have not been returned.
"""

import logging
import random

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import LedgerEntry, PayoutRequest

logger = logging.getLogger(__name__)

# Tunables — lower values for local demo; raise for production.
STUCK_THRESHOLD_SECONDS = 30
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Internal helpers (called inside transactions)
# ---------------------------------------------------------------------------


def _complete_payout_in_tx(payout: PayoutRequest) -> None:
    """Transition PROCESSING → COMPLETED. Must be called inside atomic()."""
    payout.transition_to(PayoutRequest.COMPLETED)
    payout.save(update_fields=["status", "updated_at"])
    logger.info("Payout #%s COMPLETED", payout.id)


def _fail_payout_in_tx(payout: PayoutRequest, reason: str) -> None:
    """
    Atomically transition PROCESSING → FAILED and return funds to merchant.
    Both the state change and the credit entry happen in the same transaction,
    so there is never a moment where the payout is failed but money is missing.
    """
    payout.transition_to(PayoutRequest.FAILED)
    payout.failure_reason = reason
    payout.save(update_fields=["status", "failure_reason", "updated_at"])

    LedgerEntry.objects.create(
        merchant=payout.merchant,
        amount_paise=payout.amount_paise,
        entry_type=LedgerEntry.CREDIT,
        payout=payout,
        description=f"Payout #{payout.id} failed — funds returned ({reason})",
    )
    logger.info("Payout #%s FAILED (%s). Funds returned.", payout.id, reason)


# ---------------------------------------------------------------------------
# Main processing task
# ---------------------------------------------------------------------------


@shared_task(name="payout.tasks.process_payout")
def process_payout(payout_id: int) -> None:
    """
    Pick up a PENDING payout, transition it to PROCESSING, then simulate the
    bank settlement. Called immediately after payout creation.
    """
    with transaction.atomic():
        try:
            payout = PayoutRequest.objects.select_for_update().get(
                id=payout_id, status=PayoutRequest.PENDING
            )
        except PayoutRequest.DoesNotExist:
            logger.warning("process_payout: payout #%s not PENDING — skipping.", payout_id)
            return

        payout.transition_to(PayoutRequest.PROCESSING)
        payout.processing_started_at = timezone.now()
        payout.attempt_count = 1
        payout.save(update_fields=["status", "processing_started_at", "attempt_count", "updated_at"])

    _simulate_bank_call(payout_id)


@shared_task(name="payout.tasks.retry_payout")
def retry_payout(payout_id: int) -> None:
    """
    Retry a payout that was stuck in PROCESSING. Called by check_stuck_payouts.
    Updates attempt_count and processing_started_at, then re-simulates the bank.
    """
    with transaction.atomic():
        try:
            payout = PayoutRequest.objects.select_for_update().get(
                id=payout_id, status=PayoutRequest.PROCESSING
            )
        except PayoutRequest.DoesNotExist:
            logger.warning("retry_payout: payout #%s not PROCESSING — skipping.", payout_id)
            return

        if payout.attempt_count >= MAX_ATTEMPTS:
            _fail_payout_in_tx(payout, f"Max retries ({MAX_ATTEMPTS}) exceeded")
            return

        payout.attempt_count += 1
        payout.processing_started_at = timezone.now()
        payout.save(update_fields=["attempt_count", "processing_started_at", "updated_at"])
        logger.info("Retrying payout #%s (attempt %s)", payout_id, payout.attempt_count)

    _simulate_bank_call(payout_id)


# ---------------------------------------------------------------------------
# Periodic: rescue stuck payouts
# ---------------------------------------------------------------------------


@shared_task(name="payout.tasks.check_stuck_payouts")
def check_stuck_payouts() -> None:
    """
    Celery Beat calls this every 10 seconds.
    Finds payouts stuck in PROCESSING for > STUCK_THRESHOLD_SECONDS and
    either schedules an exponential-backoff retry or terminates them.
    """
    cutoff = timezone.now() - timedelta(seconds=STUCK_THRESHOLD_SECONDS)

    stuck_payouts = PayoutRequest.objects.filter(
        status=PayoutRequest.PROCESSING,
        processing_started_at__lt=cutoff,
    ).values_list("id", "attempt_count")

    for payout_id, attempt_count in stuck_payouts:
        if attempt_count < MAX_ATTEMPTS:
            # Exponential backoff: 2s, 4s, 8s
            delay = 2 ** attempt_count
            logger.info(
                "Payout #%s stuck (attempt %s). Scheduling retry in %ss.",
                payout_id, attempt_count, delay,
            )
            retry_payout.apply_async((payout_id,), countdown=delay)
        else:
            # Max retries reached — fail atomically
            with transaction.atomic():
                try:
                    payout = PayoutRequest.objects.select_for_update().get(
                        id=payout_id, status=PayoutRequest.PROCESSING
                    )
                    _fail_payout_in_tx(payout, f"Max retries ({MAX_ATTEMPTS}) exceeded")
                except PayoutRequest.DoesNotExist:
                    pass  # Already handled by another worker


# ---------------------------------------------------------------------------
# Bank simulation
# ---------------------------------------------------------------------------


def _simulate_bank_call(payout_id: int) -> None:
    """
    Simulate an async bank settlement call.
    70% success | 20% failure | 10% hang (no-op; rescued by check_stuck_payouts)
    """
    outcome = random.random()

    if outcome < 0.70:
        with transaction.atomic():
            try:
                payout = PayoutRequest.objects.select_for_update().get(
                    id=payout_id, status=PayoutRequest.PROCESSING
                )
                _complete_payout_in_tx(payout)
            except PayoutRequest.DoesNotExist:
                logger.warning("_simulate_bank_call: payout #%s vanished before completion.", payout_id)

    elif outcome < 0.90:
        with transaction.atomic():
            try:
                payout = PayoutRequest.objects.select_for_update().get(
                    id=payout_id, status=PayoutRequest.PROCESSING
                )
                _fail_payout_in_tx(payout, "Bank declined the transfer")
            except PayoutRequest.DoesNotExist:
                logger.warning("_simulate_bank_call: payout #%s vanished before failure.", payout_id)

    else:
        # Intentional hang — check_stuck_payouts will rescue this after STUCK_THRESHOLD_SECONDS
        logger.info("Payout #%s is hanging (simulated). Will be retried by periodic task.", payout_id)
