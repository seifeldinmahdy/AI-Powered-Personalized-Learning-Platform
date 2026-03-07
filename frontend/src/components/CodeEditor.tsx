import { Play, RotateCcw, ChevronDown, CheckCircle2, Circle, Lightbulb } from 'lucide-react';
import { useState } from 'react';

export function CodeEditor() {
  const [code, setCode] = useState(`# Challenge: Create Variables
# Create three variables with the following requirements:

age = 
city = 
is_student = 

# Print all variables
print(age)
print(city)
print(is_student)`);

  const [output, setOutput] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [showHint, setShowHint] = useState(false);

  const challenges = [
    { id: 1, title: 'Variables Basics', completed: true },
    { id: 2, title: 'Data Types', completed: false, active: true },
    { id: 3, title: 'String Operations', completed: false },
    { id: 4, title: 'Type Conversion', completed: false },
  ];

  const handleRunCode = () => {
    setIsRunning(true);
    setTimeout(() => {
      setOutput(`> Running main.py...

25
San Francisco
True

> Execution complete (0.08s)
✓ All tests passed!`);
      setIsRunning(false);
    }, 1000);
  };

  const handleReset = () => {
    setCode(`# Challenge: Create Variables
# Create three variables with the following requirements:

age = 
city = 
is_student = 

# Print all variables
print(age)
print(city)
print(is_student)`);
    setOutput('');
  };

  return (
    <div className="w-1/2 border-r border-border bg-card flex flex-col">
      {/* Challenge Header */}
      <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-primary to-secondary">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="mb-1 text-white">Challenge #2</h3>
            <p className="text-sm text-white/80">Master Python Variables</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-xs font-semibold text-white">
              ⏱ 10 min
            </span>
            <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-lg text-xs font-semibold text-white">
              Easy
            </span>
          </div>
        </div>
      </div>

      {/* Challenge List - Tabs */}
      <div className="px-6 py-3 border-b border-border bg-muted/30 overflow-x-auto">
        <div className="flex gap-2">
          {challenges.map((challenge) => (
            <button
              key={challenge.id}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${
                challenge.active
                  ? 'bg-secondary text-white shadow-md'
                  : challenge.completed
                  ? 'bg-card border border-border text-foreground hover:border-secondary'
                  : 'bg-card border border-border text-muted-foreground hover:border-border'
              }`}
            >
              {challenge.completed ? (
                <CheckCircle2 size={16} className="text-accent" />
              ) : (
                <Circle size={16} />
              )}
              <span>{challenge.title}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Task Description */}
      <div className="px-6 py-4 bg-muted/30 border-b border-border">
        <h4 className="mb-3 flex items-center gap-2">
          <span className="w-6 h-6 rounded-full bg-secondary text-white text-xs flex items-center justify-center font-bold">
            1
          </span>
          Task Instructions
        </h4>
        <div className="space-y-2 text-sm text-foreground/80">
          <p>Create three variables with the following specifications:</p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li><code className="px-2 py-0.5 bg-card rounded text-xs font-mono">age</code> - An integer value (e.g., 25)</li>
            <li><code className="px-2 py-0.5 bg-card rounded text-xs font-mono">city</code> - A string value (e.g., "San Francisco")</li>
            <li><code className="px-2 py-0.5 bg-card rounded text-xs font-mono">is_student</code> - A boolean value (True or False)</li>
          </ul>
          <p className="mt-3">Then print all three variables to the console.</p>
        </div>
      </div>

      {/* Code Editor */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-6 py-3 bg-muted/30 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <div className="w-3 h-3 rounded-full bg-yellow-400" />
            <div className="w-3 h-3 rounded-full bg-green-400" />
            <span className="ml-3 text-sm font-mono">main.py</span>
          </div>
          <span className="text-xs text-muted-foreground font-mono">Python 3.11</span>
        </div>

        <div className="flex-1 flex overflow-hidden bg-[#1e1e1e]">
          {/* Line Numbers */}
          <div className="w-14 bg-[#252526] border-r border-[#3e3e42] flex flex-col py-4 text-right">
            {code.split('\n').map((_, index) => (
              <div key={index} className="px-3 text-xs font-mono text-[#858585] leading-6">
                {index + 1}
              </div>
            ))}
          </div>

          {/* Code Area */}
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="flex-1 px-4 py-4 font-mono text-sm bg-[#1e1e1e] text-[#d4d4d4] resize-none focus:outline-none leading-6"
            spellCheck={false}
            style={{ fontFamily: 'Monaco, Consolas, "Courier New", monospace' }}
          />
        </div>

        {/* Action Buttons */}
        <div className="px-6 py-4 border-t border-border bg-card flex items-center gap-3">
          <button
            onClick={handleRunCode}
            disabled={isRunning}
            className="flex-1 py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Play size={18} fill="currentColor" />
            <span>{isRunning ? 'Running...' : 'Run Code'}</span>
          </button>
          <button
            onClick={handleReset}
            className="px-4 py-3 border-2 border-border rounded-xl hover:border-secondary transition-colors"
            title="Reset Code"
          >
            <RotateCcw size={18} />
          </button>
        </div>

        {/* Output Console */}
        {output && (
          <div className="border-t border-border bg-[#1e1e1e]">
            <div className="px-6 py-3 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
              <span className="text-sm font-semibold text-[#cccccc]">Output</span>
              <span className="text-xs text-[#858585]">Console</span>
            </div>
            <div className="px-6 py-4 font-mono text-sm text-[#cccccc] max-h-40 overflow-y-auto">
              <pre className="whitespace-pre-wrap">{output}</pre>
            </div>
          </div>
        )}

        {/* Hint Section */}
        <div className="border-t border-border bg-muted/30">
          <button
            onClick={() => setShowHint(!showHint)}
            className="w-full px-6 py-3 flex items-center justify-between hover:bg-muted/50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Lightbulb size={18} className="text-accent" />
              <span className="text-sm font-medium">Need a Hint?</span>
            </div>
            <ChevronDown
              size={18}
              className={`transition-transform ${showHint ? 'rotate-180' : ''}`}
            />
          </button>
          {showHint && (
            <div className="px-6 py-4 border-t border-border bg-accent/5">
              <p className="text-sm text-foreground/80 mb-3">
                💡 <strong>Hint:</strong> In Python, you assign values to variables using the equals sign (=).
              </p>
              <div className="bg-card border border-border rounded-lg p-3">
                <code className="text-xs font-mono text-foreground">
                  variable_name = value
                </code>
              </div>
              <p className="text-sm text-foreground/80 mt-3">
                • Use quotes for strings: <code className="text-xs font-mono bg-card px-1 rounded">"text"</code><br />
                • Numbers need no quotes: <code className="text-xs font-mono bg-card px-1 rounded">25</code><br />
                • Booleans: <code className="text-xs font-mono bg-card px-1 rounded">True</code> or <code className="text-xs font-mono bg-card px-1 rounded">False</code>
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
