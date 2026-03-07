import { Play, RotateCcw, ChevronDown, Lightbulb, Code2 } from 'lucide-react';
import { useState } from 'react';
import Editor from '@monaco-editor/react';

const DEFAULT_CODE = `# Challenge: Create Variables
age = 
city = 
is_student = 

print(age)
print(city)
print(is_student)`;

export function CodePanel() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [output, setOutput] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [showHint, setShowHint] = useState(false);

  const handleRunCode = () => {
    setIsRunning(true);
    setTimeout(() => {
      setOutput(`> Running...
25
San Francisco
True
> Complete (0.08s)
✓ Tests passed!`);
      setIsRunning(false);
    }, 1000);
  };

  return (
    <div className="w-[30%] border-r-2 border-border bg-card flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-r from-primary to-secondary flex items-center justify-between">
        <div className="flex items-center gap-2 text-white">
          <Code2 size={18} />
          <h4 className="mb-0 text-white">Challenge #2</h4>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 bg-white/20 backdrop-blur-sm rounded text-xs font-semibold text-white">
            Easy
          </span>
        </div>
      </div>

      {/* Task Description */}
      <div className="px-4 py-3 bg-muted/30 border-b border-border">
        <p className="text-xs text-foreground/80 leading-relaxed">
          Create three variables: <code className="px-1 py-0.5 bg-card rounded text-xs font-mono">age</code> (integer),
          <code className="px-1 py-0.5 bg-card rounded text-xs font-mono mx-1">city</code> (string),
          and <code className="px-1 py-0.5 bg-card rounded text-xs font-mono">is_student</code> (boolean).
        </p>
      </div>

      {/* Code Editor */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-4 py-2 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-400" />
            <div className="w-2 h-2 rounded-full bg-yellow-400" />
            <div className="w-2 h-2 rounded-full bg-green-400" />
            <span className="ml-2 text-xs font-mono text-[#cccccc]">main.py</span>
          </div>
          <span className="text-xs text-[#858585] font-mono">Python</span>
        </div>

        {/* Monaco Editor replaces the old textarea */}
        <div className="flex-1 min-h-0">
          <Editor
            height="100%"
            language="python"
            theme="vs-dark"
            value={code}
            onChange={(v) => setCode(v ?? '')}
            options={{
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 14,
              lineNumbersMinChars: 3,
              padding: { top: 8, bottom: 8 },
              wordWrap: 'on',
              automaticLayout: true,
            }}
          />
        </div>

        {/* Action Buttons */}
        <div className="px-4 py-3 border-t border-border bg-card flex items-center gap-2">
          <button
            onClick={handleRunCode}
            disabled={isRunning}
            className="flex-1 py-2.5 bg-gradient-to-r from-secondary to-accent text-white rounded-lg font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 text-sm"
          >
            <Play size={16} fill="currentColor" />
            <span>{isRunning ? 'Running...' : 'Run Code'}</span>
          </button>
          <button
            onClick={() => setCode(DEFAULT_CODE)}
            className="px-3 py-2.5 border-2 border-border rounded-lg hover:border-secondary transition-colors"
            title="Reset"
          >
            <RotateCcw size={16} />
          </button>
        </div>

        {/* Output Console */}
        {output && (
          <div className="border-t border-border bg-[#1e1e1e]">
            <div className="px-4 py-2 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
              <span className="text-xs font-semibold text-[#cccccc]">Output</span>
              <button
                onClick={() => setOutput('')}
                className="text-xs text-[#858585] hover:text-[#cccccc]"
              >
                Clear
              </button>
            </div>
            <div className="px-4 py-3 font-mono text-xs text-[#cccccc] max-h-32 overflow-y-auto">
              <pre className="whitespace-pre-wrap">{output}</pre>
            </div>
          </div>
        )}

        {/* Hint Section */}
        <div className="border-t border-border">
          <button
            onClick={() => setShowHint(!showHint)}
            className="w-full px-4 py-2.5 flex items-center justify-between hover:bg-muted/30 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Lightbulb size={16} className="text-accent" />
              <span className="text-xs font-medium">Hint</span>
            </div>
            <ChevronDown
              size={16}
              className={`transition-transform ${showHint ? 'rotate-180' : ''}`}
            />
          </button>
          {showHint && (
            <div className="px-4 py-3 border-t border-border bg-accent/5">
              <p className="text-xs text-foreground/80 mb-2">
                💡 Use the equals sign to assign values:
              </p>
              <div className="bg-[#1e1e1e] rounded p-2">
                <code className="text-xs font-mono text-[#d4d4d4]">
                  name = "value"
                </code>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
