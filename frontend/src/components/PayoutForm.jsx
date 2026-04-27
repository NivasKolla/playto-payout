import { useState } from "react";
import { formatPaise } from "../utils";

export default function PayoutForm({ bankAccounts, merchantId, apiBase, onSuccess, onError }) {
  const [amount, setAmount] = useState("");
  const [bankAccountId, setBankAccountId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    const parsed = parseInt(amount, 10);
    if (!parsed || parsed <= 0) {
      onError("Enter a valid amount in paise (e.g. 50000 for ₹500)");
      return;
    }
    if (!bankAccountId) {
      onError("Select a bank account");
      return;
    }

    setSubmitting(true);

    // Generate a fresh idempotency key for each intentional submission
    const idempotencyKey = crypto.randomUUID();

    try {
      const res = await fetch(`${apiBase}/payouts/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({
          merchant_id: merchantId,
          amount_paise: parsed,
          bank_account_id: parseInt(bankAccountId, 10),
        }),
      });

      const data = await res.json();

      if (res.status === 201) {
        onSuccess(`Payout #${data.id} created for ${formatPaise(parsed)}. Processing…`);
        setAmount("");
        setBankAccountId("");
      } else {
        onError(data.error || `Error ${res.status}`);
      }
    } catch (e) {
      onError("Network error — is the backend running?");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-[#13161f] border border-[#1e2330] rounded-lg p-5">
      <h2 className="text-[10px] tracking-[0.2em] uppercase text-[#5a6480] mb-5">
        // Request Payout
      </h2>

      <div className="space-y-4">
        <div>
          <label className="block text-[10px] text-[#5a6480] mb-1.5 tracking-wide">
            Amount (paise)
          </label>
          <input
            type="number"
            placeholder="e.g. 50000 = ₹500"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full bg-[#0d0f14] border border-[#1e2330] rounded px-3 py-2 text-sm text-[#e8e4d9] placeholder-[#2a3045] focus:outline-none focus:border-[#f5a623] transition-colors"
          />
          {amount && parseInt(amount) > 0 && (
            <p className="text-[10px] text-[#f5a623] mt-1">
              = {formatPaise(parseInt(amount))}
            </p>
          )}
        </div>

        <div>
          <label className="block text-[10px] text-[#5a6480] mb-1.5 tracking-wide">
            Bank Account
          </label>
          <select
            value={bankAccountId}
            onChange={(e) => setBankAccountId(e.target.value)}
            className="w-full bg-[#0d0f14] border border-[#1e2330] rounded px-3 py-2 text-sm text-[#e8e4d9] focus:outline-none focus:border-[#f5a623] transition-colors"
          >
            <option value="">Select account…</option>
            {bankAccounts.map((ba) => (
              <option key={ba.id} value={ba.id}>
                {ba.account_holder_name} — {ba.masked_account} ({ba.ifsc_code})
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="w-full bg-[#f5a623] hover:bg-[#e09520] disabled:bg-[#3a3020] text-[#0d0f14] disabled:text-[#5a4a20] font-bold text-xs tracking-[0.15em] uppercase py-3 rounded transition-colors"
        >
          {submitting ? "Submitting…" : "→ Submit Payout"}
        </button>
      </div>

      <div className="mt-4 pt-4 border-t border-[#1e2330]">
        <p className="text-[10px] text-[#2a3045]">
          A UUID idempotency key is generated client-side per submission.
          Duplicate network retries are safe.
        </p>
      </div>
    </div>
  );
}
