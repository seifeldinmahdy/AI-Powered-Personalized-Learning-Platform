import type { InputHTMLAttributes } from 'react';

/**
 * PersonifAI labelled paper input. Uppercase tracked label over a hairline
 * `.input`. Focus state (ink-black border) is handled by the `.input:focus`
 * rule in styles/personifai.css — do not hardcode the border inline.
 */
interface PaperFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  /** Render the dark-surface variant of the input. */
  dark?: boolean;
}

export function PaperField({ label, dark = false, className = '', ...props }: PaperFieldProps) {
  return (
    <label style={{ display: 'block' }}>
      <div
        style={{
          fontFamily: 'var(--ff-body)',
          fontWeight: 500,
          fontSize: 11,
          letterSpacing: '0.15em',
          textTransform: 'uppercase',
          color: dark ? 'var(--text-primary)' : '#13100D',
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      <input className={`input ${dark ? 'input-dark' : ''} ${className}`} {...props} />
    </label>
  );
}
