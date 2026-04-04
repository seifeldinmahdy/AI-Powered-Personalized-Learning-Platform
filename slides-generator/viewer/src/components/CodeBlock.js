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

    // Copy button
    const copyBtn = document.createElement('button');
    copyBtn.className = 'code-copy-btn';
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => copyCode(codeBlock.code, copyBtn));
    header.appendChild(copyBtn);

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
