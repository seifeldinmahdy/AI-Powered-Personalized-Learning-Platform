import { useState } from 'react';
import type { CSSProperties, InputHTMLAttributes } from 'react';
import { Eye, EyeOff } from 'lucide-react';

/**
 * PersonifAI labelled paper input. Uppercase tracked label over a hairline
 * `.input`. Focus state (ink-black border) is handled by the `.input:focus`
 * rule in styles/personifai.css — do not hardcode the border inline.
 *
 * For `type="password"` an eye toggle is rendered to show/hide the value.
 */
interface PaperFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  /** Render the dark-surface variant of the input. */
  dark?: boolean;
}

export function PaperField({ label, dark = false, className = '', type, style, ...props }: PaperFieldProps) {
  const [show, setShow] = useState(false);
  const isPassword = type === 'password';
  const inputType = isPassword ? (show ? 'text' : 'password') : type;
  // Leave room for the eye button so masked text never slides under it.
  const inputStyle: CSSProperties | undefined = isPassword ? { ...style, paddingRight: 44 } : style;

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
      <div style={{ position: 'relative' }}>
        <input className={`input ${dark ? 'input-dark' : ''} ${className}`} type={inputType} style={inputStyle} {...props} />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? 'Hide password' : 'Show password'}
            title={show ? 'Hide password' : 'Show password'}
            tabIndex={-1}
            style={{
              position: 'absolute',
              top: '50%',
              right: 12,
              transform: 'translateY(-50%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 4,
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--steel-light)',
            }}
          >
            {show ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        )}
      </div>
    </label>
  );
}
