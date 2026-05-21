import { Fragment, ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "@/components/icons";

export interface Crumb {
  /** Text to display. */
  label: string;
  /** Route to navigate to. Omit for the current (last) crumb. */
  to?: string;
}

/**
 * Lightweight breadcrumb trail.
 *
 * `Home › Folders › Press` — the last crumb is rendered as plain text
 * (current location), all others as router Links. Callers pass an array
 * of `{label, to?}` items; this component handles the separators.
 */
export default function Breadcrumb({ items }: { items: Crumb[] }) {
  if (items.length === 0) return null;
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1;
        return (
          <Fragment key={`${item.label}-${idx}`}>
            {renderCrumb(item, isLast)}
            {!isLast && (
              <ChevronRight
                size={12}
                className="breadcrumb-separator"
                aria-hidden="true"
              />
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}

function renderCrumb(item: Crumb, isLast: boolean): ReactNode {
  if (isLast || !item.to) {
    return (
      <span className="breadcrumb-item current" aria-current="page">
        {item.label}
      </span>
    );
  }
  return (
    <Link to={item.to} className="breadcrumb-item">
      {item.label}
    </Link>
  );
}
