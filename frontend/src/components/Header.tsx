import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router';

interface HeaderProps {
  title: string;
  subtitle?: string;
  backLink?: string;
  backLabel?: string;
}

export function Header({ title, subtitle, backLink, backLabel = 'Back' }: HeaderProps) {
  return (
    <header className="border-b border-border bg-background px-6 py-3 shrink-0">
      <div className="flex items-center gap-4">
        {backLink && (
          <Link
            to={backLink}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors no-underline"
          >
            <ArrowLeft size={15} />
            <span>{backLabel}</span>
          </Link>
        )}
        <div>
          <p className="font-semibold text-base text-foreground leading-tight m-0">{title}</p>
          {subtitle && <p className="text-xs text-muted-foreground mt-0.5 m-0">{subtitle}</p>}
        </div>
      </div>
    </header>
  );
}
