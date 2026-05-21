import { useAuth } from "@/state/auth";
import { formatBytes } from "@/utils/format";

/**
 * Storage quota indicator pinned to the bottom of the sidebar.
 *
 * Reads `used_bytes` + `quota_bytes` directly off the auth context so the
 * caller doesn't have to wire props through the shell. The colour
 * thresholds (80% amber, 95% red) match the spec from Phase 12.
 */
export default function QuotaBar() {
  const { user } = useAuth();
  if (!user) return null;

  const { quota_bytes, used_bytes } = user;

  if (quota_bytes <= 0) {
    return (
      <div className="quota">
        <div className="quota-hint">Storage quota disabled.</div>
      </div>
    );
  }

  const percent = Math.min(100, Math.round((used_bytes / quota_bytes) * 100));
  const fillClass =
    percent >= 95 ? "quota-fill full" : percent >= 80 ? "quota-fill warn" : "quota-fill ok";

  return (
    <div className="quota" aria-label="Storage usage">
      <div className="quota-label">
        <span>Storage</span>
        <span className="quota-amount">{percent}%</span>
      </div>
      <div className="quota-track">
        <div className={fillClass} style={{ width: `${percent}%` }} />
      </div>
      <div className="quota-hint">
        {formatBytes(used_bytes)} of {formatBytes(quota_bytes)}
      </div>
    </div>
  );
}
