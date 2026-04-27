export function formatPaise(paise) {
  if (paise === null || paise === undefined) return "—";
  const rupees = Math.abs(paise) / 100;
  const sign = paise < 0 ? "−" : "";
  return `${sign}₹${rupees.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function statusColor(s) {
  return {
    pending: "#f5a623",
    processing: "#6b8afd",
    completed: "#3ddc84",
    failed: "#ff6b6b",
  }[s] || "#5a6480";
}

export function statusIcon(s) {
  return {
    pending: "○",
    processing: "◑",
    completed: "●",
    failed: "✗",
  }[s] || "?";
}
