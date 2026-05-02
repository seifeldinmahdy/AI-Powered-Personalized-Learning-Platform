import { Home, BookOpen, Brain, Code2, User, LogOut, Shield, Users, Trophy, Sun, Moon } from 'lucide-react';
import { NotificationBell } from './NotificationBell';

import { Link, useLocation, useNavigate } from 'react-router';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
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
  variant?: 'student' | 'admin' | 'instructor';
}

const studentNavItems: NavItem[] = [
  { path: '/dashboard', label: 'Home', icon: Home },
  { path: '/courses', label: 'Courses', icon: BookOpen },
  { path: '/practice', label: 'Practice', icon: Code2 },
  { path: '/leaderboard', label: 'Leaderboard', icon: Trophy },
];

const adminNavItems: NavItem[] = [
  { path: '/admin', label: 'Overview', icon: Home },
  { path: '/admin/students', label: 'Students', icon: Users },
];

const instructorNavItems: NavItem[] = [
  { path: '/instructor', label: 'My Courses', icon: BookOpen },
  { path: '/instructor/students', label: 'Students', icon: Users },
];

export function TopNav({ variant = 'student' }: TopNavProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();

  const navItems = variant === 'admin' ? adminNavItems : variant === 'instructor' ? instructorNavItems : studentNavItems;

  const isActive = (path: string) => {
    if (path === '/dashboard') return location.pathname === '/' || location.pathname === '/dashboard';
    if (path === '/admin') return location.pathname === '/admin';
    if (path === '/admin/students') return location.pathname.startsWith('/admin/students');
    if (path === '/instructor') return location.pathname === '/instructor';
    if (path === '/instructor/students') return location.pathname.startsWith('/instructor/students');
    return location.pathname.startsWith(path);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const displayName = user?.full_name || user?.username || 'User';
  const initials = displayName.slice(0, 2).toUpperCase();

  return (
    <header className="h-16 border-b border-border bg-card flex items-center px-6 shrink-0 z-40">
      {/* Left — Brand */}
      <Link
        to={variant === 'admin' ? '/admin' : variant === 'instructor' ? '/instructor' : '/dashboard'}
        className="flex items-center gap-3 no-underline flex-shrink-0"
        style={{ marginRight: '3rem' }}
      >
        {variant === 'admin' ? (
          <Shield size={26} style={{ color: 'var(--primary)' }} />
        ) : variant === 'instructor' ? (
          <BookOpen size={26} style={{ color: '#f97316' }} />
        ) : (
          <Brain size={26} style={{ color: 'var(--primary)' }} />
        )}
        <span className="font-bold text-base text-foreground whitespace-nowrap">
          {variant === 'admin' ? 'Admin Panel' : variant === 'instructor' ? 'Instructor Portal' : 'AI Learning Platform'}
        </span>
      </Link>

      {/* Center — Nav links */}
      <nav className="flex items-center gap-1 flex-1 min-w-0">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all no-underline"
              style={active ? {
                background: variant === 'instructor'
                  ? 'linear-gradient(to right, #f59e0b, #f97316)'
                  : 'linear-gradient(to right, var(--secondary), var(--accent))',
                color: '#fff',
              } : {}}
            >
              <Icon size={16} className={active ? 'text-white' : 'text-muted-foreground'} />
              <span className={active ? 'text-white' : 'text-muted-foreground'}>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Right — User area */}
      <div className="flex items-center gap-2 ml-4">
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          className="p-2 rounded-xl hover:bg-muted/60 transition-colors text-muted-foreground"
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <NotificationBell />

        {/* Avatar dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-3 px-3 py-1.5 rounded-xl hover:bg-muted/60 transition-colors">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold shadow"
                style={{ background: 'linear-gradient(135deg, var(--primary), var(--accent))' }}
              >
                {initials}
              </div>
              <div className="text-left">
                <p className="text-sm font-semibold leading-none text-foreground truncate max-w-[100px]">
                  {displayName}
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
