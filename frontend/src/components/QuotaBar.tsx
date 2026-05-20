import { formatBytes } from "@/utils/format";

interface Props {
  usedBytes: number;
  quotaBytes: number;
}

function colourFor(percent: number): string {
  if (percent >= 95) return "#d1242f"; // red
  if (percent >= 80) return "#bf8700"; // amber
  return "#1f883d"; // green
}

export default function QuotaBar({ usedBytes, quotaBytes }: Props) {
  if (quotaBytes <= 0) {
    return (
      <p style={{ color: "#6e7781", fontSize: "0.85em" }}>
        Storage: quota disabled.
      </p>
    );
  }
  const percent = Math.min(100, Math.round((usedBytes / quotaBytes) * 100));
  const fill = colourFor(percent);
  return (
    <div
      style={{
        marginBottom: "1rem",
        padding: "0.5rem 0.75rem",
        border: "1px solid #d0d7de",
        borderRadius: "6px",
        background: "#f6f8fa",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.85em",
          color: "#6e7781",
        }}
      >
        <span>
          Storage: <strong>{formatBytes(usedBytes)}</strong> of{" "}
          {formatBytes(quotaBytes)} used
        </span>
        <span>{percent}%</span>
      </div>
      <div
        style={{
          marginTop: "0.4rem",
          height: "6px",
          background: "#eaeef2",
          borderRadius: "3px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: "100%",
            background: fill,
            transition: "width 0.3s",
          }}
        />
      </div>
    </div>
  );
}
