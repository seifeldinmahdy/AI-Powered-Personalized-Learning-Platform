import { Home, BookOpen, Code2, User, LogOut, Bell, Shield } from 'lucide-react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useAuth } from '../contexts/AuthContext';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';

interface NavItem {
  path: string;
  label: string;
  icon: typeof Home;
}

interface TopNavProps {
  variant?: 'student' | 'admin';
}

const studentNavItems: NavItem[] = [
  { path: '/dashboard', label: 'Dashboard', icon: Home },
  { path: '/courses', label: 'Courses', icon: BookOpen },
  { path: '/practice', label: 'Practice', icon: Code2 },
];

const adminNavItems: NavItem[] = [
  { path: '/admin', label: 'Overview', icon: Home },
  { path: '/admin/courses', label: 'Courses', icon: BookOpen },
];

export function TopNav({ variant = 'student' }: TopNavProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const navItems = variant === 'admin' ? adminNavItems : studentNavItems;

  const isActive = (path: string) => {
    if (path === '/dashboard') return location.pathname === '/' || location.pathname === '/dashboard';
    if (path === '/admin') return location.pathname === '/admin';
    return location.pathname.startsWith(path);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const initials = user?.full_name
    ?.split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2) || 'AC';

  const brandGradient =
    variant === 'admin'
      ? 'from-rose-500 via-purple-600 to-indigo-600'
      : 'from-primary via-secondary to-accent';

  const activePill =
    variant === 'admin'
      ? 'bg-gradient-to-r from-rose-500 to-purple-600 text-white shadow-sm'
      : 'bg-gradient-to-r from-secondary to-accent text-white shadow-sm';

  return (
    <header className="h-16 border-b border-border bg-card flex items-center px-6 shrink-0 z-40">
      {/* Left — Brand */}
      <Link to={variant === 'admin' ? '/admin' : '/dashboard'} className="flex items-center gap-3 mr-10 no-underline">
        <div
          className={`w-9 h-9 rounded-xl bg-gradient-to-br ${brandGradient} flex items-center justify-center shadow-md`}
        >
          {variant === 'admin' ? (
            <Shield size={18} className="text-white" />
          ) : (
            <span className="text-white font-bold text-sm">AI</span>
          )}
        </div>
        <span className="font-bold text-base text-foreground">
          {variant === 'admin' ? 'Admin Panel' : 'AI Tutor'}
        </span>
      </Link>

      {/* Center — Nav links */}
      <nav className="flex items-center gap-1 flex-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all no-underline ${
                active
                  ? activePill
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
              }`}
            >
              <Icon size={16} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Right — User area */}
      <div className="flex items-center gap-2 ml-4">
        {/* Notification bell (placeholder) */}
        <button className="w-9 h-9 rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors">
          <Bell size={18} />
        </button>

        {/* Avatar dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2.5 px-2 py-1.5 rounded-xl hover:bg-muted/60 transition-colors">
              <div
                className={`w-8 h-8 rounded-lg bg-gradient-to-br ${brandGradient} flex items-center justify-center text-white text-xs font-bold shadow`}
              >
                {initials}
              </div>
              <div className="text-left">
                <p className="text-sm font-semibold leading-none text-foreground">
                  {user?.full_name?.split(' ')[0] || 'User'}
                </p>
                <p className="text-xs text-muted-foreground capitalize mt-0.5">
                  {user?.role || variant}
                </p>
              </div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem asChild>
              <Link to="/profile" className="flex items-center gap-2 no-underline text-foreground cursor-pointer">
                <User size={15} />
                Profile
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={handleLogout}
              className="flex items-center gap-2 text-destructive focus:text-destructive cursor-pointer"
            >
              <LogOut size={15} />
              Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
