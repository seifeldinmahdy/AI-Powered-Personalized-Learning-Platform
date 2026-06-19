/**
 * CodeBlock.js - Code block component with syntax highlighting
 */

/**
 * Render a code block with syntax highlighting
 * @param {Object} codeBlock - Code block object with language and code
 * @returns {HTMLElement} Code block element
 */
export function renderCodeBlock(codeBlock) {
    const container = document.createElement('div');
    container.className = 'code-block';

    // Header with language label
    const header = document.createElement('div');
    header.className = 'code-header';

    const languageLabel = document.createElement('span');
    languageLabel.className = 'code-language';
    languageLabel.textContent = codeBlock.language || 'code';
    header.appendChild(languageLabel);

    // "Generated example" badge — synthesized snippet, not literal source code
    if (codeBlock.generated) {
        const badge = document.createElement('span');
        badge.className = 'code-generated-badge';
        badge.textContent = 'EXAMPLE';
        header.appendChild(badge);
    }

    const actions = document.createElement('div');
    actions.className = 'code-actions';

    // Run button — reveals the demonstrative output (LLM-written, NOT executed)
    const hasOutput = codeBlock.runnable && typeof codeBlock.output === 'string';
    let runBtn = null;
    if (hasOutput) {
        runBtn = document.createElement('button');
        runBtn.className = 'code-run-btn';
        runBtn.textContent = 'Run';
        actions.appendChild(runBtn);
    }

    // Copy button
    const copyBtn = document.createElement('button');
    copyBtn.className = 'code-copy-btn';
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => copyCode(codeBlock.code, copyBtn));
    actions.appendChild(copyBtn);

    header.appendChild(actions);
    container.appendChild(header);

    // Code content
    const content = document.createElement('div');
    content.className = 'code-content';

    const pre = document.createElement('pre');
    const code = document.createElement('code');

    // Add Prism.js language class
    const langClass = getPrismLanguageClass(codeBlock.language);
    code.className = langClass;
    code.textContent = codeBlock.code || '';

    pre.appendChild(code);
    content.appendChild(pre);
    container.appendChild(content);

    // Demonstrative output panel (hidden until "Run" is clicked)
    if (hasOutput && runBtn) {
        const outputPanel = document.createElement('div');
        outputPanel.className = 'code-output';
        outputPanel.style.display = 'none';

        const outputLabel = document.createElement('div');
        outputLabel.className = 'code-output-label';
        outputLabel.textContent = '▶ OUTPUT';
        outputPanel.appendChild(outputLabel);

        const outputPre = document.createElement('pre');
        const outputCode = document.createElement('code');
        outputCode.textContent = codeBlock.output || '(no output)';
        outputPre.appendChild(outputCode);
        outputPanel.appendChild(outputPre);
        container.appendChild(outputPanel);

        runBtn.addEventListener('click', () => {
            const showing = outputPanel.style.display !== 'none';
            outputPanel.style.display = showing ? 'none' : 'block';
            runBtn.textContent = showing ? 'Run' : 'Hide';
        });
    }

    // Trigger Prism.js highlighting after render
    requestAnimationFrame(() => {
        if (window.Prism) {
            Prism.highlightElement(code);
        }
    });

    return container;
}

/**
 * Get Prism.js language class
 * @param {string} language - Language name
 * @returns {string} Prism language class
 */
function getPrismLanguageClass(language) {
    const languageMap = {
        'python': 'language-python',
        'py': 'language-python',
        'javascript': 'language-javascript',
        'js': 'language-javascript',
        'java': 'language-java',
        'c': 'language-c',
        'cpp': 'language-cpp',
        'c++': 'language-cpp',
        'html': 'language-html',
        'css': 'language-css',
        'json': 'language-json',
        'bash': 'language-bash',
        'shell': 'language-bash'
    };

    const lang = (language || '').toLowerCase();
    return languageMap[lang] || 'language-plaintext';
}

/**
 * Copy code to clipboard
 * @param {string} code - Code to copy
 * @param {HTMLElement} button - Copy button for feedback
 */
async function copyCode(code, button) {
    try {
        await navigator.clipboard.writeText(code);
        button.textContent = 'Copied!';
        setTimeout(() => {
            button.textContent = 'Copy';
        }, 2000);
    } catch (e) {
        console.error('Failed to copy:', e);
        button.textContent = 'Failed';
    }
}
