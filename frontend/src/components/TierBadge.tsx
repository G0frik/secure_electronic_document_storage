import { ClassificationResult, Tier } from "@/api/files";

const TIER_CLASS: Record<Tier, string> = {
  public: "badge badge-public",
  internal: "badge badge-internal",
  confidential: "badge badge-confidential",
  restricted: "badge badge-restricted",
};

const TIER_LABEL: Record<Tier, string> = {
  public: "Public",
  internal: "Internal",
  confidential: "Confidential",
  restricted: "Restricted",
};

interface Props {
  classification?: ClassificationResult | null;
  loading?: boolean;
  onClick?: () => void;
}

/**
 * Sensitivity tier indicator.
 *
 * Colours preserved verbatim from the original — they're the only chromatic
 * vocabulary in the redesign and carry semantic meaning. The wrapper class
 * is `.badge` which gives the pill shape + mono uppercase letterspacing.
 */
export default function TierBadge({ classification, loading, onClick }: Props) {
  if (
    loading ||
    !classification ||
    classification.status === "pending" ||
    classification.status === "running"
  ) {
    return <span className="badge badge-pending">classifying…</span>;
  }

  if (classification.status === "failed") {
    return (
      <span
        className="badge badge-failed"
        title={classification.error_message ?? "classification failed"}
      >
        Failed
      </span>
    );
  }

  if (!classification.final_tier) {
    return <span className="badge badge-pending">—</span>;
  }

  const tooltip = (classification.categories_triggered ?? []).join(", ") || undefined;

  if (onClick) {
    return (
      <button
        type="button"
        className={`${TIER_CLASS[classification.final_tier]} badge-interactive`}
        title={tooltip}
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
      >
        {TIER_LABEL[classification.final_tier]}
      </button>
    );
  }

  return (
    <span className={TIER_CLASS[classification.final_tier]} title={tooltip}>
      {TIER_LABEL[classification.final_tier]}
    </span>
  );
}
