# Playto Payout Engine

A minimal payout engine for Indian agencies and freelancers collecting international payments.  
Money flow: **USD in → Playto → INR out to merchant's bank account**.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Django 4.2 + Django REST Framework |
| Frontend | React 18 + Tailwind CSS + Vite |
| Database | PostgreSQL 15 |
| Task queue | Celery 5 + Redis |
| Beat scheduler | Celery Beat (periodic tasks) |

---

## Quick Start (Docker — recommended)

```bash
git clone https://github.com/yourname/playto-payout.git
cd playto-payout

# Copy env and edit if needed
cp .env.example .env

# Start all services (db, redis, api, worker, beat, frontend)
docker compose up --build -d

# Run migrations + seed data
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed
docker compose exec api python manage.py createsuperuser  # optional

# Open
open http://localhost:3000   # Frontend dashboard
open http://localhost:8000/admin  # Django admin
```

---

## Manual Setup (local dev)

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Set env vars (or export individually)
export DB_HOST=localhost DB_NAME=playto DB_USER=playto DB_PASSWORD=playto
export REDIS_URL=redis://localhost:6379/0
export DEBUG=True

python manage.py migrate
python manage.py seed
python manage.py runserver 8000

# In separate terminals:
celery -A playto worker --loglevel=info
celery -A playto beat --loglevel=info
```

### Frontend

```bash
cd frontend
npm install
# Point at local backend
echo "VITE_API_URL=http://localhost:8000/api/v1" > .env.local
npm run dev
# Open http://localhost:3000
```

---

## API Reference

### `GET /api/v1/merchants/`
List all merchants.

### `GET /api/v1/merchants/:id/`
Full dashboard: balance, held, ledger entries, payout history, bank accounts.

### `POST /api/v1/payouts/`
Create a payout request.

**Headers:**
```
Idempotency-Key: <uuid-v4>      # Required. Unique per request intent.
Content-Type: application/json
```

**Body:**
```json
{
  "merchant_id": 1,
  "amount_paise": 50000,
  "bank_account_id": 1
}
```

**Responses:**
- `201 Created` — payout created, funds held
- `422 Unprocessable Entity` — insufficient balance
- `400 Bad Request` — missing/invalid fields

Calling with the **same `Idempotency-Key`** returns the exact same response as the first call (no duplicate payout).

---

## Running Tests

```bash
cd backend
python manage.py test payout
```

Test coverage:
- **Concurrency**: two simultaneous 60-rupee requests on 100-rupee balance → exactly 1 succeeds
- **Idempotency**: same key → same response, no duplicate payout
- **State machine**: all illegal transitions raise `ValueError`
- **Balance invariant**: `SUM(credits) - SUM(debits) == balance`

---

## Payout Lifecycle

```
POST /payouts/
      │
      ▼
  [PENDING] ──── process_payout task ────► [PROCESSING]
                                                │
                        70% success ────────────┤────► [COMPLETED]
                        20% failure ────────────┤────► [FAILED] + credit returned
                        10% hang ───────────────┘
                                                │
                    check_stuck_payouts (10s) ──┘
                    retries up to 3× with 2^n backoff
                    then → [FAILED] + credit returned
```

## Deployment (Railway)

```bash
# Install Railway CLI
npm install -g @railway/cli
railway login
railway init
railway add postgresql redis
railway up
railway run python manage.py migrate
railway run python manage.py seed
```

Set these environment variables in the Railway dashboard:
- `SECRET_KEY`
- `DATABASE_URL` (auto-set by Railway PostgreSQL plugin)
- `REDIS_URL` (auto-set by Railway Redis plugin)
- `ALLOWED_HOSTS` (your Railway domain)
- `DEBUG=False`
