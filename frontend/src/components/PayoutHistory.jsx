import { formatPaise, formatDate, statusColor, statusIcon } from "../utils";

export default function PayoutHistory({ payouts }) {
  return (
    <div className="bg-[#13161f] border border-[#1e2330] rounded-lg overflow-hidden">
      <div className="px-5 py-3 border-b border-[#1e2330]">
        <h2 className="text-[10px] tracking-[0.2em] uppercase text-[#5a6480]">
          // Payout History
        </h2>
      </div>

      {payouts.length === 0 ? (
        <div className="px-5 py-8 text-center text-[#2a3045] text-xs">
          No payouts yet
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#1e2330]">
                {["ID", "Amount", "Status", "Attempts", "Bank", "Created"].map((h) => (
                  <th
                    key={h}
                    className="text-left px-4 py-2.5 text-[#3a4155] text-[10px] tracking-wide uppercase font-normal"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {payouts.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-[#1a1d26] hover:bg-[#0d0f14] transition-colors"
                >
                  <td className="px-4 py-3 text-[#5a6480]">#{p.id}</td>
                  <td className="px-4 py-3 font-bold text-[#e8e4d9]">
                    {formatPaise(p.amount_paise)}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide"
                      style={{ color: statusColor(p.status) }}
                    >
                      <StatusDot status={p.status} />
                      {p.status.toUpperCase()}
                    </span>
                    {p.failure_reason && (
                      <p className="text-[10px] text-[#ff6b6b] mt-0.5 max-w-[120px] truncate">
                        {p.failure_reason}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-[#5a6480]">{p.attempt_count}</td>
                  <td className="px-4 py-3 text-[#5a6480]">
                    {p.bank_account?.masked_account || "—"}
                  </td>
                  <td className="px-4 py-3 text-[#5a6480]">{formatDate(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusDot({ status }) {
  const colors = {
    pending: "bg-[#f5a623]",
    processing: "bg-[#6b8afd] animate-pulse",
    completed: "bg-[#3ddc84]",
    failed: "bg-[#ff6b6b]",
  };
  return (
    <span className={`inline-block w-1.5 h-1.5 rounded-full ${colors[status] || "bg-gray-500"}`} />
  );
}
