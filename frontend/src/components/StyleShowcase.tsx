import { Terminal, Code, Zap, Database, Settings, Search } from 'lucide-react';

export function StyleShowcase() {
  return (
    <div className="max-w-7xl mx-auto p-8">
      {/* Header */}
      <header className="border-b border-border pb-8 mb-12">
        <h1 className="mb-3">Minimalist Design System</h1>
        <p className="text-base opacity-70">
          Professional, distraction-free, coding-focused interface
        </p>
      </header>

      {/* Typography Section */}
      <section className="mb-16">
        <h2 className="mb-6">Typography</h2>
        <div className="space-y-4 bg-secondary p-6 border border-border">
          <h1>Heading 1 - Bold & Impactful</h1>
          <h2>Heading 2 - Clear Hierarchy</h2>
          <h3>Heading 3 - Section Headers</h3>
          <h4>Heading 4 - Subsections</h4>
          <p className="mt-4">
            Body text with optimal readability. Clean sans-serif typography ensures
            maximum clarity and professional appearance. High contrast for distraction-free
            reading experience.
          </p>
        </div>
      </section>

      {/* Components Grid */}
      <section className="mb-16">
        <h2 className="mb-6">Components</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Card 1 */}
          <div className="border border-border bg-card p-6 hover:border-foreground transition-colors">
            <Terminal className="mb-4" size={32} />
            <h3 className="mb-2">Terminal</h3>
            <p className="text-sm opacity-70">Command-line interface tools</p>
          </div>

          {/* Card 2 */}
          <div className="border border-border bg-card p-6 hover:border-foreground transition-colors">
            <Code className="mb-4" size={32} />
            <h3 className="mb-2">Code Editor</h3>
            <p className="text-sm opacity-70">Syntax highlighting & formatting</p>
          </div>

          {/* Card 3 */}
          <div className="border border-border bg-card p-6 hover:border-foreground transition-colors">
            <Zap className="mb-4" size={32} />
            <h3 className="mb-2">Performance</h3>
            <p className="text-sm opacity-70">Lightning-fast execution</p>
          </div>

          {/* Card 4 */}
          <div className="border border-border bg-card p-6 hover:border-foreground transition-colors">
            <Database className="mb-4" size={32} />
            <h3 className="mb-2">Database</h3>
            <p className="text-sm opacity-70">Data management & queries</p>
          </div>

          {/* Card 5 */}
          <div className="border border-border bg-card p-6 hover:border-foreground transition-colors">
            <Settings className="mb-4" size={32} />
            <h3 className="mb-2">Configuration</h3>
            <p className="text-sm opacity-70">System settings & preferences</p>
          </div>

          {/* Card 6 */}
          <div className="border border-border bg-card p-6 hover:border-foreground transition-colors">
            <Search className="mb-4" size={32} />
            <h3 className="mb-2">Search</h3>
            <p className="text-sm opacity-70">Find anything instantly</p>
          </div>
        </div>
      </section>

      {/* Buttons */}
      <section className="mb-16">
        <h2 className="mb-6">Buttons</h2>
        <div className="flex flex-wrap gap-4">
          <button className="px-6 py-3 bg-primary text-primary-foreground border border-primary hover:bg-transparent hover:text-foreground transition-colors">
            Primary Action
          </button>
          <button className="px-6 py-3 border border-border bg-transparent hover:border-foreground transition-colors">
            Secondary
          </button>
          <button className="px-6 py-3 bg-secondary border border-border hover:border-foreground transition-colors">
            Muted
          </button>
          <button className="px-6 py-3 border border-border bg-transparent opacity-50 cursor-not-allowed">
            Disabled
          </button>
        </div>
      </section>

      {/* Form Elements */}
      <section className="mb-16">
        <h2 className="mb-6">Form Elements</h2>
        <div className="max-w-md space-y-6 bg-secondary p-6 border border-border">
          <div>
            <label className="block mb-2">Email Address</label>
            <input
              type="email"
              placeholder="user@example.com"
              className="w-full px-4 py-3 border border-input bg-input-background focus:outline-none focus:border-foreground transition-colors"
            />
          </div>
          <div>
            <label className="block mb-2">Password</label>
            <input
              type="password"
              placeholder="Enter password"
              className="w-full px-4 py-3 border border-input bg-input-background focus:outline-none focus:border-foreground transition-colors"
            />
          </div>
          <div>
            <label className="block mb-2">Description</label>
            <textarea
              placeholder="Enter description..."
              rows={4}
              className="w-full px-4 py-3 border border-input bg-input-background focus:outline-none focus:border-foreground transition-colors resize-none"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="terms"
              className="w-5 h-5 border border-input bg-input-background accent-foreground"
            />
            <label htmlFor="terms" className="text-sm">
              Accept terms and conditions
            </label>
          </div>
        </div>
      </section>

      {/* Data Table */}
      <section className="mb-16">
        <h2 className="mb-6">Data Table</h2>
        <div className="border border-border overflow-hidden">
          <table className="w-full">
            <thead className="bg-secondary border-b border-border">
              <tr>
                <th className="px-6 py-4 text-left">ID</th>
                <th className="px-6 py-4 text-left">Name</th>
                <th className="px-6 py-4 text-left">Status</th>
                <th className="px-6 py-4 text-left">Priority</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border hover:bg-secondary transition-colors">
                <td className="px-6 py-4 font-mono text-sm">001</td>
                <td className="px-6 py-4">Initialize Database</td>
                <td className="px-6 py-4">
                  <span className="px-3 py-1 border border-border bg-card text-sm">Active</span>
                </td>
                <td className="px-6 py-4">High</td>
              </tr>
              <tr className="border-b border-border hover:bg-secondary transition-colors">
                <td className="px-6 py-4 font-mono text-sm">002</td>
                <td className="px-6 py-4">Configure API</td>
                <td className="px-6 py-4">
                  <span className="px-3 py-1 border border-border bg-card text-sm">Pending</span>
                </td>
                <td className="px-6 py-4">Medium</td>
              </tr>
              <tr className="hover:bg-secondary transition-colors">
                <td className="px-6 py-4 font-mono text-sm">003</td>
                <td className="px-6 py-4">Deploy System</td>
                <td className="px-6 py-4">
                  <span className="px-3 py-1 border border-border bg-card text-sm">Complete</span>
                </td>
                <td className="px-6 py-4">Low</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Code Block */}
      <section className="mb-16">
        <h2 className="mb-6">Code Block</h2>
        <div className="border border-border bg-card p-6">
          <pre className="font-mono text-sm overflow-x-auto">
            <code>{`function minimalistDesign() {
  const colors = {
    background: '#FFFFFF',
    text: '#000000',
    border: '#E5E5E5'
  };
  
  return {
    professional: true,
    distractionFree: true,
    highTech: true
  };
}`}</code>
          </pre>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border pt-8 mt-16">
        <p className="text-sm opacity-70 text-center">
          Minimalist Black & White Design System — Professional & Coding-Focused
        </p>
      </footer>
    </div>
  );
}
