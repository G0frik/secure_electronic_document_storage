import { ClassificationResult, StoredFile, Tier } from "@/api/files";
import Drawer from "@/components/Drawer";
import { formatDateTime } from "@/utils/format";

interface Props {
  file: StoredFile;
  classification: ClassificationResult | null;
  open: boolean;
  onClose: () => void;
}

const TIER_LABEL: Record<Tier, string> = {
  public: "Public",
  internal: "Internal",
  confidential: "Confidential",
  restricted: "Restricted",
};

const TIER_CLASS: Record<Tier, string> = {
  public: "badge badge-public",
  internal: "badge badge-internal",
  confidential: "badge badge-confidential",
  restricted: "badge badge-restricted",
};

const CATEGORY_METADATA: Record<
  string,
  { name: string; tier: Tier; threshold: number }
> = {
  "personally identifiable information": {
    name: "Personally identifiable information (PII)",
    tier: "restricted",
    threshold: 0.70,
  },
  "payment card data": {
    name: "Payment card data",
    tier: "restricted",
    threshold: 0.70,
  },
  "authentication credentials": {
    name: "Authentication credentials",
    tier: "restricted",
    threshold: 0.70,
  },
  "medical records": {
    name: "Medical records",
    tier: "restricted",
    threshold: 0.70,
  },
  "salary": {
    name: "Salary, compensation records",
    tier: "confidential",
    threshold: 0.50,
  },
  "proprietary technology": {
    name: "Proprietary technology / code",
    tier: "confidential",
    threshold: 0.50,
  },
  "non-public business strategy": {
    name: "Non-public M&A / deals",
    tier: "confidential",
    threshold: 0.50,
  },
  "internal business operations": {
    name: "Internal office memos / drafts",
    tier: "internal",
    threshold: 0.35,
  },
  "publicly available marketing material": {
    name: "Public marketing / info",
    tier: "public",
    threshold: 0.35,
  },
};

const ENTITY_TIERS: Record<string, string> = {
  US_SSN: "restricted",
  CREDIT_CARD: "restricted",
  IBAN_CODE: "restricted",
  US_BANK_NUMBER: "restricted",
  US_PASSPORT: "restricted",
  US_DRIVER_LICENSE: "restricted",
  MEDICAL_LICENSE: "restricted",
  CRYPTO: "restricted",
  CREDENTIAL: "restricted",
  RNOKPP: "restricted",
  UA_PASSPORT: "restricted",
  UA_PHONE: "confidential",
  EMAIL_ADDRESS: "confidential",
  PHONE_NUMBER: "confidential",
  PERSON: "confidential",
  LOCATION: "confidential",
  NRP: "confidential",
  IP_ADDRESS: "internal",
  URL: "internal",
  DATE_TIME: "public",
};

export default function ClassificationDetailsDrawer({
  file,
  classification,
  open,
  onClose,
}: Props) {
  if (!classification) {
    return null;
  }

  const finalTier = classification.final_tier || "public";
  const rawScores = classification.raw_scores || {};
  const presidioEntities = classification.presidio_entities || {};

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Classification Details"
      subtitle={<span className="filename">{file.original_filename}</span>}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        {/* Tier Row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontWeight: 600, fontSize: "0.875rem", color: "var(--color-ink)" }}>
            Final Sensitivity Tier:
          </span>
          <span className={TIER_CLASS[finalTier]}>
            {TIER_LABEL[finalTier]}
          </span>
        </div>

        {/* Zero-Shot Progress Bars Card */}
        <div className="zero-shot-card">
          <div className="zero-shot-title">
            Zero-Shot Categories (NLI v6)
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {Object.entries(CATEGORY_METADATA).map(([key, meta]) => {
              const score = rawScores[key] ?? 0;
              const triggered = score >= meta.threshold;
              let barColor = "var(--color-muted-soft)";
              if (triggered) {
                if (meta.tier === "restricted") barColor = "var(--tier-restricted-fg)";
                else if (meta.tier === "confidential") barColor = "var(--tier-confidential-fg)";
                else if (meta.tier === "internal") barColor = "var(--tier-internal-fg)";
                else if (meta.tier === "public") barColor = "var(--tier-public-fg)";
              }
              const pctScore = Math.round(score * 100);
              const pctThreshold = Math.round(meta.threshold * 100);

              return (
                <div key={key} style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: "3px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 500, color: triggered ? "var(--color-ink)" : "var(--color-muted)" }}>
                      {meta.name}
                    </span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.7rem", fontWeight: 600, color: barColor }}>
                      {pctScore}% (thresh {pctThreshold}%)
                    </span>
                  </div>
                  <div style={{ height: "6px", background: "var(--color-line)", borderRadius: "3px", position: "relative", overflow: "visible" }}>
                    <div style={{ width: `${pctScore}%`, height: "100%", borderRadius: "3px", background: barColor }} />
                    <div
                      style={{
                        position: "absolute",
                        left: `${pctThreshold}%`,
                        top: "-2px",
                        height: "10px",
                        width: "2px",
                        background: "var(--color-ink)",
                        zIndex: 2,
                      }}
                      title="Threshold"
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Presidio Detected Entities Card */}
        <div className="zero-shot-card">
          <div className="zero-shot-title">
            Presidio Detected Entities
          </div>
          {Object.keys(presidioEntities).length === 0 ? (
            <div style={{ fontSize: "0.8125rem", color: "var(--color-muted)" }}>
              No entities detected.
            </div>
          ) : (
            <table className="table" style={{ fontSize: "0.8rem", width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1.5px solid var(--color-line-strong)" }}>
                  <th style={{ padding: "var(--space-2) 0", fontSize: "0.7rem", color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.04em" }}>Entity Type</th>
                  <th style={{ padding: "var(--space-2) 0", fontSize: "0.7rem", color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }}>Count</th>
                  <th style={{ padding: "var(--space-2) 0", fontSize: "0.7rem", color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "right" }}>Max Score</th>
                  <th style={{ padding: "var(--space-2) 0", fontSize: "0.7rem", color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.04em", paddingLeft: "10px" }}>Samples</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(presidioEntities).map(([entityType, details]) => {
                  const tier = ENTITY_TIERS[entityType] || "confidential";
                  let scoreColor = "var(--color-success)";
                  if (tier === "restricted") scoreColor = "var(--tier-restricted-fg)";
                  else if (tier === "confidential") scoreColor = "var(--tier-confidential-fg)";
                  else if (tier === "internal") scoreColor = "var(--tier-internal-fg)";

                  return (
                    <tr key={entityType} style={{ borderBottom: "1px solid var(--color-line)" }}>
                      <td style={{ padding: "var(--space-2) 0" }}>
                        <code style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", background: "var(--color-accent-soft)", padding: "1px 4px", borderRadius: "2px" }}>
                          {entityType}
                        </code>
                      </td>
                      <td style={{ padding: "var(--space-2) 0", textAlign: "center" }}>
                        {details.count}
                      </td>
                      <td style={{ padding: "var(--space-2) 0", textAlign: "right", color: scoreColor, fontWeight: 600 }}>
                        {details.max_score.toFixed(2)}
                      </td>
                      <td style={{ padding: "var(--space-2) 0", paddingLeft: "10px" }}>
                        <code style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                          {details.samples.join(", ")}
                        </code>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Metadata Footer */}
        <div style={{ fontSize: "0.75rem", color: "var(--color-muted)", display: "flex", flexDirection: "column", gap: "var(--space-1)", marginTop: "auto", paddingTop: "var(--space-4)", borderTop: "1px dashed var(--color-line)" }}>
          <div>Classifier Engine: <code style={{ fontFamily: "var(--font-mono)" }}>{classification.classifier_version || "unknown"}</code></div>
          {classification.classified_at && (
            <div>Scanned at: <span style={{ fontFamily: "var(--font-mono)" }}>{formatDateTime(classification.classified_at)}</span></div>
          )}
        </div>
      </div>
    </Drawer>
  );
}
