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
    <header className="border-b border-border bg-background px-8 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          {backLink && (
            <Link
              to={backLink}
              className="flex items-center gap-2 px-3 py-2 border border-border hover:border-foreground transition-colors"
            >
              <ArrowLeft size={16} />
              <span className="text-sm">{backLabel}</span>
            </Link>
          )}
          <div>
            <h2 className="mb-0">{title}</h2>
            {subtitle && <p className="text-sm opacity-70">{subtitle}</p>}
          </div>
        </div>
      </div>
    </header>
  );
}
