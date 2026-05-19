export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = n / 1024;
  for (const u of units) {
    if (size < 1024) return `${size.toFixed(size < 10 ? 2 : 1)} ${u}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} PB`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}
