import type { ButtonHTMLAttributes } from 'react';

/**
 * PersonifAI button. Maps to the design-system `.btn` family in
 * styles/personifai.css. Variants: primary (ink), red (accent-blue),
 * paper (ink on paper), ghost (outlined), ghost-dark (steel outline).
 */
export type PaiButtonVariant = 'primary' | 'red' | 'paper' | 'ghost' | 'ghost-dark';

interface PaiButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: PaiButtonVariant;
}

export function PaiButton({
  variant = 'primary',
  className = '',
  children,
  ...props
}: PaiButtonProps) {
  return (
    <button className={`btn btn-${variant} ${className}`} {...props}>
      {children}
    </button>
  );
}
