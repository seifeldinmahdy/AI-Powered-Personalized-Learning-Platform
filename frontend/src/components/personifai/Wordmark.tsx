/**
 * PersonifAI wordmark — square indicator + "PERSONIFAI" lockup.
 * Shared across every redesigned screen (auth, dashboard, session, …).
 */
interface WordmarkProps {
  /** Text color of the lockup. */
  color?: string;
  /** Color of the leading square indicator. */
  dot?: string;
  /** Suffix after PERSONIFAI, e.g. "· PLACEMENT". */
  suffix?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function Wordmark({
  color = '#1A1611',
  dot = '#2563EB',
  suffix,
  className = '',
  style,
}: WordmarkProps) {
  return (
    <span className={`wordmark ${className}`} style={{ color, ...style }}>
      <span
        style={{ width: 8, height: 8, background: dot, display: 'inline-block', flexShrink: 0 }}
      />
      PERSONIFAI{suffix ? ` ${suffix}` : ''}
    </span>
  );
}
