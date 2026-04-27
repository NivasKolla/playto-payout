import random
from celery import shared_task
from django.utils import timezone
from django.db import transaction
from payouts.models import Payout, IdempotencyKey
from payouts.services import PayoutService


@shared_task
def process_pending_payouts():
    """Process all pending payouts.
    
    Simulates bank settlement:
    - 70% succeed
    - 20% fail
    - 10% stay in processing
    """
    pending_payouts = Payout.objects.filter(status='pending')
    
    for payout in pending_payouts:
        try:
            PayoutService.mark_processing(payout)
            
            rand = random.random()
            if rand < 0.70:
                PayoutService.mark_completed(payout)
            elif rand < 0.90:
                PayoutService.mark_failed(payout, error_message='Bank rejected settlement')
        except Exception as e:
            print(f"Error processing payout {payout.id}: {str(e)}")


@shared_task
def retry_stuck_payouts():
    """Retry payouts stuck in processing for 30+ seconds."""
    stuck_threshold = timezone.now() - timezone.timedelta(seconds=30)
    
    stuck_payouts = Payout.objects.filter(
        status='processing',
        last_attempted_at__lt=stuck_threshold
    )
    
    for payout in stuck_payouts:
        try:
            if payout.attempt_count >= payout.max_attempts:
                PayoutService.mark_failed(
                    payout,
                    error_message='Max retry attempts exceeded'
                )
            else:
                payout.status = 'pending'
                payout.save()
        except Exception as e:
            print(f"Error retrying payout {payout.id}: {str(e)}")


@shared_task
def cleanup_old_idempotency_keys():
    """Delete expired idempotency keys."""
    expired = IdempotencyKey.objects.filter(
        expires_at__lt=timezone.now()
    )
    count, _ = expired.delete()
    return f"Deleted {count} expired idempotency keys"
