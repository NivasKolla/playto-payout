# EXPLAINER.md — Playto Payout Engine

---

## 1. The Ledger

### Balance calculation query

```python
# payout/models.py — Merchant.get_balance_paise()

from django.db.models import BigIntegerField, Sum, Case, When, F

def get_balance_paise(self):
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
```

This generates a **single SQL query**:

```sql
SELECT SUM(
  CASE
    WHEN entry_type = 'credit' THEN amount_paise
    WHEN entry_type = 'debit'  THEN -amount_paise
  END
) AS balance
FROM payout_ledgerentry
WHERE merchant_id = %s;
```

### Why this model?

**Why a separate LedgerEntry table (not a `balance` column on Merchant)?**

A mutable `balance` column on Merchant is dangerous: two concurrent transactions can both read `balance = 10000`, both subtract 6000, and both write `4000` back — classic lost-update problem. A ledger is append-only; you never update existing rows, only insert new ones. The balance is *derived* at query time from immutable history.

**Why credits and debits as rows with an `entry_type`, not two separate tables?**

A single table makes the balance query trivially a one-liner SUM with a CASE. Two tables would require a UNION or two subqueries. Also, each entry can link to a `payout` FK for full auditability.

**Why `BigIntegerField` for `amount_paise`?**

`FloatField` and `DecimalField` have representation issues in aggregations. `BigIntegerField` is exact integer arithmetic at every layer — Python, PostgreSQL, and JSON serialisation. ₹21,47,483.647 is the max rupee value at 32-bit int precision; `BigIntegerField` gives us 9,223,372,036,854 — far beyond any plausible merchant balance.

**Invariant check:**

```
SUM of all CREDIT entries − SUM of all DEBIT entries = get_balance_paise()
```

This is always true by construction. We never manipulate the balance column directly.

---

## 2. The Lock

### Exact code that prevents concurrent overdraft

```python
# payout/views.py — CreatePayoutView.post()

with transaction.atomic():
    # This single line is the concurrency guarantee.
    # PostgreSQL acquires a row-level exclusive lock on the Merchant row.
    # Any other transaction attempting select_for_update on the same merchant
    # will BLOCK until this transaction commits or rolls back.
    merchant_locked = Merchant.objects.select_for_update().get(id=merchant_id)

    # All subsequent reads and writes in this transaction see a consistent
    # snapshot. No other transaction can interleave between the balance
    # check and the LedgerEntry insert.
    available = merchant_locked.get_balance_paise()   # DB-level SUM

    if available < amount_paise:
        return Response({"error": "Insufficient balance"}, status=422)

    payout = PayoutRequest.objects.create(...)
    LedgerEntry.objects.create(entry_type=LedgerEntry.DEBIT, ...)  # holds funds
    IdempotencyKey.objects.create(...)
# ← lock released on commit
```

### Database primitive

`SELECT ... FOR UPDATE` — a PostgreSQL row-level exclusive lock. When Transaction A holds this lock on the Merchant row, Transaction B's `SELECT FOR UPDATE` blocks until A commits. Only then does B re-read the balance — which now reflects A's debit — and correctly sees insufficient funds.

**Why lock the Merchant row and not the LedgerEntry table?**

The Merchant row is the single contention point for all payout operations for a given merchant. Locking it serialises all concurrent payout requests for that merchant. An alternative (advisory locks, e.g. `pg_advisory_xact_lock(merchant_id)`) would also work but is less idiomatic in Django.

**Scenario proof:**

```
T1 (₹60 request):  BEGIN
                   SELECT merchant FOR UPDATE  ← acquires lock
T2 (₹60 request):  BEGIN
                   SELECT merchant FOR UPDATE  ← BLOCKS (waits for T1)

T1:                balance = 10,000   (DB SUM)
T1:                10,000 >= 6,000   ✓
T1:                INSERT payout, INSERT debit ledger entry
T1:                COMMIT  ← lock released

T2:                ← unblocked, re-reads merchant
T2:                balance = 4,000   (reflects T1's debit)
T2:                4,000 < 6,000   ✗
T2:                RETURN 422 Insufficient Balance
T2:                COMMIT (nothing to roll back)
```

---

## 3. The Idempotency

### How the system knows it has seen a key before

We have an `IdempotencyKey` model with a `unique_together = [("merchant", "key")]` database constraint. The check happens inside the **same `transaction.atomic()` block** as the payout creation:

```python
# Step 1 — fast path: check before acquiring the merchant lock
existing = IdempotencyKey.objects.filter(
    merchant=merchant,
    key=idempotency_key,
    expires_at__gt=now,
    response_status__gt=0,   # only return committed responses
).first()
if existing:
    return Response(existing.response_body, status=existing.response_status)

# Step 2 — inside the atomic block, after creating the payout:
IdempotencyKey.objects.create(
    merchant=merchant_locked,
    key=idempotency_key,
    response_body=resp_body,
    response_status=resp_status,
    expires_at=now + timedelta(hours=24),
)
```

The idempotency key record is created **inside the same transaction** as the payout and ledger entry. Either all three rows exist, or none do — crash-safe.

### What happens when the second request arrives while the first is in flight?

There are three cases:

**Case A — Transaction 1 has not committed yet.**
Both requests hit the fast-path check (no key exists), proceed into the `transaction.atomic()`, and both acquire the `select_for_update` merchant lock — but only one at a time. The second request blocks on the merchant lock until the first commits. Once T1 commits, T2 unblocks, sees the idempotency key exists (fast-path check) OR tries to INSERT and gets a `UNIQUE constraint` violation caught by the `IntegrityError` handler.

**Case B — T1 committed; T2 hits the fast-path check.**
T2 reads the committed `IdempotencyKey` row and returns `existing.response_body` directly. No lock needed.

**Case C — IntegrityError race** (sub-millisecond window).
Both T1 and T2 pass the fast-path check simultaneously. T1 inserts the key. T2 attempts to insert the same key and gets `IntegrityError`. The `except IntegrityError` block catches this, fetches the committed row, and returns it:

```python
except IntegrityError:
    committed = IdempotencyKey.objects.get(merchant=merchant, key=idempotency_key)
    return Response(committed.response_body, status=committed.response_status)
```

Keys are **scoped per merchant** (`unique_together` includes `merchant_id`). The same UUID from two different merchants creates two independent `IdempotencyKey` rows. Keys expire after 24 hours (`expires_at` filter + a cleanup job can prune old rows).

---

## 4. The State Machine

### Where illegal transitions are blocked

```python
# payout/models.py — PayoutRequest.transition_to()

VALID_TRANSITIONS = {
    "pending":    ["processing"],
    "processing": ["completed", "failed"],
    "completed":  [],   # terminal — no transitions out
    "failed":     [],   # terminal — no transitions out
}

def transition_to(self, new_status: str) -> None:
    allowed = self.VALID_TRANSITIONS.get(self.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Illegal state transition: {self.status} → {new_status}. "
            f"Allowed from '{self.status}': {allowed or 'none (terminal state)'}"
        )
    self.status = new_status
```

**`failed → completed` is blocked here**: `VALID_TRANSITIONS["failed"]` is an empty list. Any attempt to call `payout.transition_to("completed")` on a failed payout raises `ValueError` immediately — before any database write.

**`completed → anything` is blocked here**: Same mechanism. `VALID_TRANSITIONS["completed"]` is `[]`.

Every place that changes payout status goes through `transition_to()`:

```python
# tasks.py — _complete_payout_in_tx()
payout.transition_to(PayoutRequest.COMPLETED)   # raises if not PROCESSING

# tasks.py — _fail_payout_in_tx()
payout.transition_to(PayoutRequest.FAILED)      # raises if not PROCESSING
```

### Atomic fund return on failure

The fund return (credit ledger entry) happens **in the same database transaction** as the status change:

```python
def _fail_payout_in_tx(payout, reason):
    # Both writes or neither — enforced by transaction.atomic() in the caller
    payout.transition_to(PayoutRequest.FAILED)
    payout.failure_reason = reason
    payout.save(update_fields=["status", "failure_reason", "updated_at"])

    LedgerEntry.objects.create(
        merchant=payout.merchant,
        amount_paise=payout.amount_paise,
        entry_type=LedgerEntry.CREDIT,          # returns the held funds
        payout=payout,
        description=f"Payout #{payout.id} failed — funds returned",
    )
```

If the process crashes between the `save()` and the `LedgerEntry.objects.create()`, the entire transaction rolls back — the payout stays PROCESSING and the periodic task retries it. Funds are never silently lost.

---

## 5. The AI Audit

### What AI gave me (subtly wrong aggregation)

When I asked for the balance calculation, the first AI suggestion was:

```python
# AI's initial version — WRONG
def get_balance_paise(self):
    credits = self.ledger_entries.filter(entry_type='credit').aggregate(
        total=Sum('amount_paise')
    )['total'] or 0

    debits = self.ledger_entries.filter(entry_type='debit').aggregate(
        total=Sum('amount_paise')
    )['total'] or 0

    return credits - debits   # ← Python arithmetic on two fetched values
```

**What's wrong with this?**

1. **Two round-trips to the database** instead of one. Every balance check now costs 2× the query overhead.

2. **Race condition under concurrent writes.** If a `DEBIT` ledger entry is inserted between the first `aggregate()` call and the second `aggregate()` call (possible when two Python threads run this without a transaction), the `credits` total reflects a world where the debit hasn't happened yet, but the `debits` total has it. The result is momentarily inflated. In a transaction with `READ COMMITTED` isolation (PostgreSQL's default), each statement sees the committed state at statement time — so two statements in the same function can see different states.

3. **Not atomic with the lock.** The spec requires that the balance check and the deduction happen in a single database operation under the merchant row lock. With two separate queries, another transaction could insert a debit entry between them, making the balance check stale.

**What I replaced it with:**

```python
# My version — correct
def get_balance_paise(self):
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
```

**One query. One consistent snapshot. No Python arithmetic on fetched rows.**

The `CASE` expression runs entirely inside PostgreSQL's aggregation engine. When called inside `transaction.atomic()` with `select_for_update()` on the merchant row, this single query is guaranteed to see all committed entries up to the moment the lock was acquired — and no entries from concurrent transactions that haven't committed yet.

A secondary issue: AI also initially used `DecimalField` for `amount_paise`. I caught this and switched to `BigIntegerField`. `DecimalField` in PostgreSQL stores `NUMERIC`, which requires more storage and has slower arithmetic than `BIGINT`. Since paise is always a whole number, `BigIntegerField` (PostgreSQL `BIGINT`) is strictly correct and faster.
