import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Merchant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="BankAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("account_number", models.CharField(max_length=20)),
                ("ifsc_code", models.CharField(max_length=11)),
                ("account_holder_name", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bank_accounts", to="payout.merchant")),
            ],
        ),
        migrations.CreateModel(
            name="PayoutRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_paise", models.BigIntegerField()),
                ("status", models.CharField(
                    choices=[("pending","Pending"),("processing","Processing"),("completed","Completed"),("failed","Failed")],
                    default="pending", max_length=20,
                )),
                ("idempotency_key", models.UUIDField()),
                ("attempt_count", models.IntegerField(default=0)),
                ("failure_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("processing_started_at", models.DateTimeField(blank=True, null=True)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payout_requests", to="payout.merchant")),
                ("bank_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="payout.bankaccount")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="LedgerEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_paise", models.BigIntegerField()),
                ("entry_type", models.CharField(choices=[("credit","Credit"),("debit","Debit")], max_length=10)),
                ("description", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ledger_entries", to="payout.merchant")),
                ("payout", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ledger_entries", to="payout.payoutrequest")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="IdempotencyKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.UUIDField()),
                ("response_body", models.JSONField(default=dict)),
                ("response_status", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="payout.merchant")),
            ],
        ),
        migrations.AlterUniqueTogether(
            name="idempotencykey",
            unique_together={("merchant", "key")},
        ),
        migrations.AddIndex(
            model_name="idempotencykey",
            index=models.Index(fields=["merchant", "key"], name="payout_idem_merchan_key_idx"),
        ),
        migrations.AddIndex(
            model_name="idempotencykey",
            index=models.Index(fields=["expires_at"], name="payout_idem_expires_idx"),
        ),
    ]
