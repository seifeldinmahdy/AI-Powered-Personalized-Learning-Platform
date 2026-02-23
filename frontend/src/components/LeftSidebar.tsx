import { User, BookOpen, Code, Database, GitBranch, FileCode } from 'lucide-react';
import { CircularProgress } from './CircularProgress';

export function LeftSidebar() {
  const modules = [
    { id: 1, name: 'Introduction', completed: true, icon: BookOpen },
    { id: 2, name: 'Variables & Data Types', active: true, icon: Code },
    { id: 3, name: 'Control Flow', completed: false, icon: GitBranch },
    { id: 4, name: 'Functions', completed: false, icon: FileCode },
    { id: 5, name: 'Data Structures', completed: false, icon: Database },
  ];

  return (
    <aside className="w-80 border-r border-border bg-background flex flex-col">
      {/* Header */}
      <div className="px-6 py-6 border-b border-border">
        <h2 className="mb-1">AI Tutor</h2>
        <p className="text-sm opacity-70">Learning Management System</p>
      </div>

      {/* User Profile */}
      <div className="px-6 py-6 border-b border-border">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-12 h-12 border-2 border-foreground bg-secondary flex items-center justify-center">
            <User size={24} />
          </div>
          <div>
            <h4 className="mb-0">Alex Chen</h4>
            <p className="text-sm opacity-70">Student</p>
          </div>
        </div>

        {/* Circular Progress */}
        <div className="flex items-center gap-4">
          <CircularProgress percentage={45} />
          <div>
            <p className="text-sm opacity-70">Course Progress</p>
            <h4 className="mb-0">Python 101</h4>
          </div>
        </div>
      </div>

      {/* Course Modules */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-4">
          <h4 className="mb-4">Course Modules</h4>
          <nav className="space-y-1">
            {modules.map((module) => {
              const Icon = module.icon;
              return (
                <div
                  key={module.id}
                  className={`
                    flex items-center gap-3 px-4 py-3 border transition-colors cursor-pointer
                    ${module.active 
                      ? 'border-foreground bg-foreground text-background' 
                      : 'border-border bg-background hover:border-foreground'
                    }
                  `}
                >
                  <Icon size={18} />
                  <span className="flex-1 text-sm">{module.name}</span>
                  {module.completed && (
                    <span className="text-xs">✓</span>
                  )}
                </div>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Footer Stats */}
      <div className="px-6 py-4 border-t border-border">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="font-mono text-xl">12</p>
            <p className="text-xs opacity-70">Lessons</p>
          </div>
          <div>
            <p className="font-mono text-xl">8</p>
            <p className="text-xs opacity-70">Complete</p>
          </div>
          <div>
            <p className="font-mono text-xl">4</p>
            <p className="text-xs opacity-70">Remaining</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
