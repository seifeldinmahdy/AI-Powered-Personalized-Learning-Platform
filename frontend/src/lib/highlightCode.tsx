import type { ReactNode } from 'react';

// Minimal, dependency-free syntax highlighter (VS Code "Dark+" palette). Good
// enough to make Python/JS snippets read like real code. Shared by the slides
// viewer and the coding lab so read-only code blocks look consistent.
export const CODE_COLORS = {
  comment: '#6A9955',
  string: '#CE9178',
  number: '#B5CEA8',
  keyword: '#569CD6',
  builtin: '#4EC9B0',
  func: '#DCDCAA',
  plain: '#D4D4D4',
};

const CODE_TOKEN_RE = new RegExp(
  [
    '(#[^\\n]*|//[^\\n]*)',                                   // 1 comment
    '("(?:[^"\\\\]|\\\\.)*"|\'(?:[^\'\\\\]|\\\\.)*\'|`(?:[^`\\\\]|\\\\.)*`)', // 2 string
    '\\b(\\d+(?:\\.\\d+)?)\\b',                               // 3 number
    '\\b(def|class|return|if|elif|else|for|while|in|import|from|as|with|try|except|finally|raise|lambda|yield|pass|break|continue|and|or|not|is|None|True|False|const|let|var|function|new|typeof|async|await|of|export|default|this)\\b', // 4 keyword
    '\\b(print|len|range|int|str|float|bool|list|dict|set|tuple|sum|max|min|map|filter|sorted|enumerate|zip|abs|round|open|input|console|Math|JSON|Array|Object)\\b', // 5 builtin
    '([A-Za-z_]\\w*)(?=\\s*\\()',                             // 6 function call
  ].join('|'),
  'g',
);

export function highlightCode(code: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  CODE_TOKEN_RE.lastIndex = 0;
  while ((m = CODE_TOKEN_RE.exec(code)) !== null) {
    if (m.index > last) out.push(code.slice(last, m.index));
    const full = m[0];
    const color = m[1] ? CODE_COLORS.comment
      : m[2] ? CODE_COLORS.string
      : m[3] ? CODE_COLORS.number
      : m[4] ? CODE_COLORS.keyword
      : m[5] ? CODE_COLORS.builtin
      : CODE_COLORS.func;
    out.push(<span key={key++} style={{ color }}>{full}</span>);
    last = m.index + full.length;
    if (m.index === CODE_TOKEN_RE.lastIndex) CODE_TOKEN_RE.lastIndex++; // guard zero-width
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}
