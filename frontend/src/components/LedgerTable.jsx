import { formatPaise, formatDate } from "../utils";

export default function LedgerTable({ entries }) {
  return (
    <div className="bg-[#13161f] border border-[#1e2330] rounded-lg overflow-hidden">
      <div className="px-5 py-3 border-b border-[#1e2330]">
        <h2 className="text-[10px] tracking-[0.2em] uppercase text-[#5a6480]">
          // Ledger Entries
        </h2>
      </div>

      {entries.length === 0 ? (
        <div className="px-5 py-8 text-center text-[#2a3045] text-xs">No entries</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#1e2330]">
                {["Type", "Amount", "Description", "Payout", "Date"].map((h) => (
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
              {entries.map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-[#1a1d26] hover:bg-[#0d0f14] transition-colors"
                >
                  <td className="px-4 py-2.5">
                    <span
                      className={`text-[10px] font-bold tracking-wide ${
                        e.entry_type === "credit"
                          ? "text-[#3ddc84]"
                          : "text-[#ff6b6b]"
                      }`}
                    >
                      {e.entry_type === "credit" ? "+ CR" : "− DR"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-bold text-[#e8e4d9]">
                    {formatPaise(e.amount_paise)}
                  </td>
                  <td className="px-4 py-2.5 text-[#5a6480] max-w-[180px] truncate">
                    {e.description}
                  </td>
                  <td className="px-4 py-2.5 text-[#3a4155]">
                    {e.payout_id ? `#${e.payout_id}` : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-[#3a4155]">{formatDate(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
