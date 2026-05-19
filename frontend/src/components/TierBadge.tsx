import { ClassificationResult, Tier } from "@/api/files";

const TIER_STYLE: Record<Tier, { bg: string; fg: string; label: string }> = {
  public: { bg: "#dafbe1", fg: "#1a7f37", label: "PUBLIC" },
  internal: { bg: "#ddf4ff", fg: "#0969da", label: "INTERNAL" },
  confidential: { bg: "#fff8c5", fg: "#9a6700", label: "CONFIDENTIAL" },
  restricted: { bg: "#ffebe9", fg: "#cf222e", label: "RESTRICTED" },
};

const PENDING_STYLE = { bg: "#eaeef2", fg: "#6e7781", label: "classifying…" };
const FAILED_STYLE = { bg: "#ffebe9", fg: "#cf222e", label: "FAILED" };

const BASE: React.CSSProperties = {
  display: "inline-block",
  padding: "0.15rem 0.5rem",
  borderRadius: "999px",
  fontSize: "0.75em",
  fontWeight: 600,
  letterSpacing: "0.02em",
};

interface Props {
  classification?: ClassificationResult | null;
  loading?: boolean;
}

export default function TierBadge({ classification, loading }: Props) {
  if (loading || !classification || classification.status === "pending" || classification.status === "running") {
    return (
      <span style={{ ...BASE, background: PENDING_STYLE.bg, color: PENDING_STYLE.fg }}>
        {PENDING_STYLE.label}
      </span>
    );
  }

  if (classification.status === "failed") {
    return (
      <span
        style={{ ...BASE, background: FAILED_STYLE.bg, color: FAILED_STYLE.fg }}
        title={classification.error_message ?? "classification failed"}
      >
        {FAILED_STYLE.label}
      </span>
    );
  }

  if (!classification.final_tier) {
    return (
      <span style={{ ...BASE, background: PENDING_STYLE.bg, color: PENDING_STYLE.fg }}>—</span>
    );
  }

  const style = TIER_STYLE[classification.final_tier];
  const tooltip = (classification.categories_triggered ?? []).join(", ") || undefined;
  return (
    <span
      style={{ ...BASE, background: style.bg, color: style.fg }}
      title={tooltip}
    >
      {style.label}
    </span>
  );
}
