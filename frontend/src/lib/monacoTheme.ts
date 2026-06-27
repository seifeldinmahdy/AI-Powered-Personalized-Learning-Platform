// Shared Monaco editor theme that matches the platform's "codex" design system
// (warm paper/ink palette) instead of Monaco's stock cold `vs-dark` (#1e1e1e),
// which clashed with the warm `--code-bg` (#1A1611) surfaces around the editor.
//
// Use on any <Editor>:  beforeMount={defineCodexTheme} theme={CODEX_MONACO_THEME}
import type { Monaco } from '@monaco-editor/react';

export const CODEX_MONACO_THEME = 'codex-dark';

// Monaco measures its own font, so pass a concrete family (not a CSS var).
export const CODEX_MONACO_FONT = "'JetBrains Mono', ui-monospace, 'SFMono-Regular', monospace";

let _defined = false;

export function defineCodexTheme(monaco: Monaco): void {
    // defineTheme is idempotent, but guard so repeated mounts don't re-run it.
    if (_defined) return;
    monaco.editor.defineTheme(CODEX_MONACO_THEME, {
        base: 'vs-dark',
        inherit: true,
        rules: [
            { token: '', foreground: 'EDE4D3' },
            { token: 'comment', foreground: '8A8174', fontStyle: 'italic' },
            { token: 'keyword', foreground: '7FA8F0' },
            { token: 'keyword.control', foreground: '7FA8F0' },
            { token: 'string', foreground: '8FCBA1' },
            { token: 'number', foreground: 'E0A36B' },
            { token: 'type', foreground: 'A6CFF5' },
            { token: 'type.identifier', foreground: 'A6CFF5' },
            { token: 'function', foreground: 'F1EADB' },
            { token: 'variable', foreground: 'EDE4D3' },
            { token: 'constant', foreground: 'E0A36B' },
            { token: 'delimiter', foreground: 'A89E8C' },
            { token: 'operator', foreground: 'A89E8C' },
        ],
        colors: {
            'editor.background': '#1A1611',
            'editor.foreground': '#EDE4D3',
            'editorLineNumber.foreground': '#5C5446',
            'editorLineNumber.activeForeground': '#A89E8C',
            'editorCursor.foreground': '#2563EB',
            'editor.selectionBackground': '#33291B',
            'editor.lineHighlightBackground': '#211C14',
            'editor.selectionHighlightBackground': '#33291B80',
            'editorWhitespace.foreground': '#332C20',
            'editorIndentGuide.background': '#2A2419',
            'editorIndentGuide.activeBackground': '#3A3224',
            'editorGutter.background': '#1A1611',
            'editorWidget.background': '#211C14',
            'editorWidget.border': '#332C20',
            'editorSuggestWidget.background': '#211C14',
            'input.background': '#211C14',
            'scrollbarSlider.background': '#33291B80',
            'scrollbarSlider.hoverBackground': '#33291BB0',
        },
    });
    _defined = true;
}
