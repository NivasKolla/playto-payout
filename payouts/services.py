from django.db import transaction
from django.utils import timezone
from payouts.models import Merchant, Payout, MerchantLedger


class PayoutService:
    @staticmethod
    @transaction.atomic
    def create_payout(merchant, amount_paise, bank_account):
        """Create a payout with concurrency protection.
        
        Uses SELECT FOR UPDATE to prevent concurrent overdrafts.
        Raises ValueError if insufficient balance.
        """
        merchant = Merchant.objects.select_for_update().get(id=merchant.id)
        
        available = merchant.available_balance_paise
        if available < amount_paise:
            raise ValueError(f"Insufficient balance. Available: {available}, Requested: {amount_paise}")
        
        payout = Payout.objects.create(
            merchant=merchant,
            amount_paise=amount_paise,
            bank_account=bank_account,
            status='pending'
        )
        
        return payout
    
    @staticmethod
    @transaction.atomic
    def mark_processing(payout):
        """Transition payout from pending to processing."""
        payout = Payout.objects.select_for_update().get(id=payout.id)
        
        if not payout.can_transition_to('processing'):
            raise ValueError(f"Cannot transition from {payout.status} to processing")
        
        payout.status = 'processing'
        payout.last_attempted_at = timezone.now()
        payout.attempt_count += 1
        payout.save()
        return payout
    
    @staticmethod
    @transaction.atomic
    def mark_completed(payout):
        """Transition payout from processing to completed."""
        payout = Payout.objects.select_for_update().get(id=payout.id)
        
        if not payout.can_transition_to('completed'):
            raise ValueError(f"Cannot transition from {payout.status} to completed")
        
        payout.status = 'completed'
        payout.completed_at = timezone.now()
        payout.save()
        return payout
    
    @staticmethod
    @transaction.atomic
    def mark_failed(payout, error_message=''):
        """Transition payout from processing to failed and return funds.
        
        Atomic: state change + credit ledger entry in same transaction.
        """
        payout = Payout.objects.select_for_update().get(id=payout.id)
        
        if not payout.can_transition_to('failed'):
            raise ValueError(f"Cannot transition from {payout.status} to failed")
        
        MerchantLedger.objects.create(
            merchant=payout.merchant,
            entry_type='credit',
            amount_paise=payout.amount_paise,
            description=f"Refund for failed payout {payout.id}",
            related_payout=payout
        )
        
        payout.status = 'failed'
        payout.completed_at = timezone.now()
        payout.error_message = error_message
        payout.save()
        return payout
