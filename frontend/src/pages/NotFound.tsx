import { Link } from 'react-router';
import { Home } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <h1 className="mb-4 font-mono">404</h1>
        <h2 className="mb-4">Page Not Found</h2>
        <p className="mb-8 opacity-70">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <Link
          to="/dashboard"
          className="inline-flex items-center gap-2 px-6 py-3 bg-foreground text-background border-2 border-foreground hover:bg-transparent hover:text-foreground transition-colors"
        >
          <Home size={18} />
          <span>Back to Dashboard</span>
        </Link>
      </div>
    </div>
  );
}
