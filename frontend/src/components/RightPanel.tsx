import { Play, ChevronDown } from 'lucide-react';
import { useState } from 'react';

export function RightPanel() {
  const [code, setCode] = useState(`# Write your code here
x = 5
name = "Python"

print(x)
print(name)`);
  const [showHint, setShowHint] = useState(false);

  return (
    <aside className="w-96 border-l border-border bg-background flex flex-col">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border">
        <h3 className="mb-1">Challenge #1</h3>
        <p className="text-sm opacity-70">Practice Exercise</p>
      </div>

      {/* Challenge Description */}
      <div className="px-6 py-4 border-b border-border bg-secondary">
        <h5 className="mb-3">Task:</h5>
        <p className="text-sm mb-4">
          Create three variables: <code className="font-mono bg-background border border-border px-2 py-1">age</code> (integer), 
          <code className="font-mono bg-background border border-border px-2 py-1 mx-1">city</code> (string), 
          and <code className="font-mono bg-background border border-border px-2 py-1">is_student</code> (boolean). 
          Print all three variables.
        </p>
        <div className="flex items-center gap-2 text-xs">
          <span className="px-2 py-1 border border-border bg-background">Difficulty: Easy</span>
          <span className="px-2 py-1 border border-border bg-background">⏱ 5 min</span>
        </div>
      </div>

      {/* Code Editor */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-6 py-3 border-b border-border bg-secondary flex items-center justify-between">
          <span className="text-sm">main.py</span>
          <span className="text-xs opacity-70 font-mono">Python 3.11</span>
        </div>

        <div className="flex-1 flex overflow-hidden bg-background">
          {/* Line Numbers */}
          <div className="w-12 bg-secondary border-r border-border flex flex-col py-4 text-right">
            {code.split('\n').map((_, index) => (
              <div key={index} className="px-3 text-xs font-mono opacity-50 leading-6">
                {index + 1}
              </div>
            ))}
          </div>

          {/* Code Area */}
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="flex-1 px-4 py-4 font-mono text-sm bg-background resize-none focus:outline-none leading-6"
            spellCheck={false}
            style={{ fontFamily: 'Monaco, Consolas, "Courier New", monospace' }}
          />
        </div>

        {/* Run Button */}
        <div className="px-6 py-4 border-t border-border">
          <button className="w-full py-3 bg-foreground text-background hover:bg-transparent hover:text-foreground border-2 border-foreground transition-colors flex items-center justify-center gap-2">
            <Play size={18} fill="currentColor" />
            <span>Run Code</span>
          </button>
        </div>

        {/* Output Console */}
        <div className="border-t border-border bg-secondary">
          <div className="px-6 py-3 border-b border-border flex items-center justify-between">
            <span className="text-sm">Output</span>
            <span className="text-xs opacity-70">Console</span>
          </div>
          <div className="px-6 py-4 font-mono text-sm min-h-[100px] max-h-[150px] overflow-y-auto">
            <div className="opacity-70">&gt; Running main.py...</div>
            <div className="mt-2">5</div>
            <div>Python</div>
            <div className="mt-2 opacity-70">&gt; Execution complete (0.12s)</div>
          </div>
        </div>

        {/* Hint Accordion */}
        <div className="border-t border-border">
          <button
            onClick={() => setShowHint(!showHint)}
            className="w-full px-6 py-4 flex items-center justify-between hover:bg-secondary transition-colors"
          >
            <span className="text-sm">Need a Hint?</span>
            <ChevronDown 
              size={18} 
              className={`transition-transform ${showHint ? 'rotate-180' : ''}`}
            />
          </button>
          {showHint && (
            <div className="px-6 py-4 border-t border-border bg-secondary">
              <p className="text-sm opacity-70 mb-3">
                Remember the syntax for creating variables:
              </p>
              <pre className="font-mono text-xs bg-background border border-border p-3">
                <code>{`variable_name = value`}</code>
              </pre>
              <p className="text-sm opacity-70 mt-3">
                Use quotes for strings, no quotes for numbers, and True/False for booleans.
              </p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
