import { useState, useEffect, useCallback } from "react";
import { formatPaise, formatDate, statusColor, statusIcon } from "./utils";
import PayoutForm from "./components/PayoutForm";
import LedgerTable from "./components/LedgerTable";
import PayoutHistory from "./components/PayoutHistory";

const API =   `${import.meta.env.VITE_API_BASE}/api/v1`;

export default function App() {
  const [merchants, setMerchants] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [flash, setFlash] = useState(null);

  // Load merchant list once
  useEffect(() => {
    fetch(`${API}/merchants/`)
      .then((r) => r.json())
      .then((data) => {
        setMerchants(data);
        if (data.length > 0) setSelectedId(data[0].id);
      })
      .catch(() => setFlash({ type: "error", text: "Could not reach backend." }));
  }, []);

  // Poll dashboard every 4 seconds for live status updates
  const fetchDashboard = useCallback(() => {
    if (!selectedId) return;
    fetch(`${API}/merchants/${selectedId}/`)
      .then((r) => r.json())
      .then((data) => {
        setDashboard(data);
        setLoading(false);
      })
      .catch(() => {});
  }, [selectedId]);

  useEffect(() => {
    setLoading(true);
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 4000);
    return () => clearInterval(interval);
  }, [fetchDashboard, refreshKey]);

  const onPayoutSuccess = (msg) => {
    setFlash({ type: "success", text: msg });
    setTimeout(() => setFlash(null), 4000);
    setTimeout(() => setRefreshKey((k) => k + 1), 600);
  };

  const onPayoutError = (msg) => {
    setFlash({ type: "error", text: msg });
    setTimeout(() => setFlash(null), 5000);
  };

  const merchant = dashboard?.merchant;
  const balance = merchant?.balance_paise ?? 0;
  const held = merchant?.held_paise ?? 0;
  const available = merchant?.available_paise ?? 0;

  return (
    <div className="min-h-screen bg-[#0d0f14] text-[#e8e4d9] font-['IBM_Plex_Mono',monospace]">
      {/* Header */}
      <header className="border-b border-[#1e2330] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 bg-[#f5a623] rotate-45" />
          <span className="text-[#f5a623] text-sm font-bold tracking-[0.2em] uppercase">
            Playto Pay
          </span>
          <span className="text-[#3a4155] text-xs ml-2">// Payout Engine</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[#3a4155] text-xs">merchant</span>
          <select
            className="bg-[#13161f] border border-[#1e2330] text-[#e8e4d9] text-xs px-3 py-1.5 rounded focus:outline-none focus:border-[#f5a623] transition-colors"
            value={selectedId || ""}
            onChange={(e) => setSelectedId(Number(e.target.value))}
          >
            {merchants.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>
      </header>

      {/* Flash Banner */}
      {flash && (
        <div
          className={`px-6 py-3 text-xs font-bold tracking-wide ${
            flash.type === "success"
              ? "bg-[#0d2b1a] text-[#3ddc84] border-b border-[#1a4a2a]"
              : "bg-[#2b0d0d] text-[#ff6b6b] border-b border-[#4a1a1a]"
          }`}
        >
          {flash.type === "success" ? "✓ " : "✗ "}{flash.text}
        </div>
      )}

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        {/* Balance Cards */}
        <div className="grid grid-cols-3 gap-4">
          <BalanceCard
            label="Total Balance"
            value={formatPaise(balance)}
            sub="credits − debits"
            accent="#f5a623"
          />
          <BalanceCard
            label="Held (in-flight)"
            value={formatPaise(held)}
            sub="pending + processing"
            accent="#6b8afd"
          />
          <BalanceCard
            label="Net Available"
            value={formatPaise(available - held)}
            sub="withdrawable now"
            accent="#3ddc84"
          />
        </div>

        <div className="grid grid-cols-5 gap-6">
          {/* Left: Payout Form + History */}
          <div className="col-span-2 space-y-6">
            <PayoutForm
              bankAccounts={dashboard?.bank_accounts || []}
              merchantId={selectedId}
              apiBase={API}
              onSuccess={onPayoutSuccess}
              onError={onPayoutError}
            />
            <LiveIndicator />
          </div>

          {/* Right: Ledger + Payouts */}
          <div className="col-span-3 space-y-6">
            <PayoutHistory payouts={dashboard?.payouts || []} />
            <LedgerTable entries={dashboard?.ledger_entries || []} />
          </div>
        </div>
      </main>
    </div>
  );
}

function BalanceCard({ label, value, sub, accent }) {
  return (
    <div className="bg-[#13161f] border border-[#1e2330] rounded-lg p-5 relative overflow-hidden">
      <div
        className="absolute top-0 left-0 w-1 h-full"
        style={{ background: accent }}
      />
      <p className="text-[#5a6480] text-[10px] tracking-[0.15em] uppercase mb-2 ml-1">{label}</p>
      <p className="text-2xl font-bold ml-1" style={{ color: accent }}>
        {value}
      </p>
      <p className="text-[#3a4155] text-[10px] mt-1 ml-1">{sub}</p>
    </div>
  );
}

function LiveIndicator() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 4000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="flex items-center gap-2 text-[#3a4155] text-[10px]">
      <span className="w-1.5 h-1.5 rounded-full bg-[#3ddc84] animate-pulse" />
      polling every 4s — last sync #{tick}
    </div>
  );
}
