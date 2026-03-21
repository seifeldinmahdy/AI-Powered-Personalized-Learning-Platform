import { Play, RotateCcw, ChevronDown, Lightbulb, Code2, CheckCircle2, XCircle } from 'lucide-react';
import { useState } from 'react';
import Editor from '@monaco-editor/react';
import { evaluateCode, type EvaluateCodeResponse } from '../services/coding';

export interface CodePanelChallenge {
  problem_text: string;
  starter_code: string;
  hint_text?: string;
}

interface CodePanelProps {
  challenge?: CodePanelChallenge;
}

const DEFAULT_CHALLENGE: CodePanelChallenge = {
  problem_text: 'Create three variables: age (integer), city (string), and is_student (boolean).',
  starter_code: `# Challenge: Create Variables\nage = \ncity = \nis_student = \n\nprint(age)\nprint(city)\nprint(is_student)`,
  hint_text: 'Use the equals sign to assign values: name = "value"',
};

export function CodePanel({ challenge }: CodePanelProps) {
  const activeChallenge = challenge ?? DEFAULT_CHALLENGE;
  const [code, setCode] = useState(activeChallenge.starter_code);
  const [output, setOutput] = useState('');
  const [feedback, setFeedback] = useState<EvaluateCodeResponse | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [showHint, setShowHint] = useState(false);

  const handleRunCode = async () => {
    setIsRunning(true);
    setOutput('');
    setFeedback(null);
    try {
      const result = await evaluateCode(activeChallenge.problem_text, code);
      setFeedback(result);
      setOutput(result.feedback);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Evaluation failed';
      setOutput(`Error: ${msg}`);
    } finally {
      setIsRunning(false);
    }
  };

  const handleReset = () => {
    setCode(activeChallenge.starter_code);
    setOutput('');
    setFeedback(null);
  };

  return (
    <div className="w-[30%] border-r-2 border-border bg-card flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-r from-primary to-secondary flex items-center justify-between">
        <div className="flex items-center gap-2 text-white">
          <Code2 size={18} />
          <h4 className="mb-0 text-white">Code Challenge</h4>
        </div>
      </div>

      {/* Task Description */}
      <div className="px-4 py-3 bg-muted/30 border-b border-border">
        <p className="text-xs text-foreground/80 leading-relaxed">
          {activeChallenge.problem_text}
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

        {/* Monaco Editor */}
        <div className="flex-1 min-h-0">
          <Editor
            height="100%"
            language="python"
            theme="vs-dark"
            value={code}
            onChange={(val) => setCode(val ?? '')}
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
            <span>{isRunning ? 'Evaluating...' : 'Submit Code'}</span>
          </button>
          <button
            onClick={handleReset}
            className="px-3 py-2.5 border-2 border-border rounded-lg hover:border-secondary transition-colors"
            title="Reset"
          >
            <RotateCcw size={16} />
          </button>
        </div>

        {/* Feedback / Output Console */}
        {(output || feedback) && (
          <div className="border-t border-border bg-[#1e1e1e]">
            {feedback && (
              <div className={`px-4 py-2 flex items-center gap-2 ${
                feedback.status === 'Pass'
                  ? 'bg-green-50 border-b border-green-200'
                  : 'bg-red-50 border-b border-red-200'
              }`}>
                {feedback.status === 'Pass' ? (
                  <CheckCircle2 size={16} className="text-green-600" />
                ) : (
                  <XCircle size={16} className="text-red-600" />
                )}
                <span className={`text-xs font-semibold ${
                  feedback.status === 'Pass' ? 'text-green-700' : 'text-red-700'
                }`}>
                  {feedback.status === 'Pass' ? 'Passed' : 'Needs Work'}
                </span>
              </div>
            )}
            <div className="px-4 py-2 bg-[#252526] border-b border-[#3e3e42] flex items-center justify-between">
              <span className="text-xs font-semibold text-[#cccccc]">Feedback</span>
              <button
                onClick={() => { setOutput(''); setFeedback(null); }}
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
        {activeChallenge.hint_text && (
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
                <p className="text-xs text-foreground/80">
                  {activeChallenge.hint_text}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
