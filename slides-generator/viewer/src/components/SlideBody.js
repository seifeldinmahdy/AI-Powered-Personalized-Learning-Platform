/**
 * SlideBody.js - Body content component with highlight types
 *
 * Handles definitions (term + description) and standard bullet points.
 */

import { getHighlightClass } from '../utils/parseSlide.js';

/**
 * Render slide body content (bullet points and definitions)
 * @param {Array} bodyContent - Array of content items
 * @returns {HTMLElement} Body content element
 */
export function renderSlideBody(bodyContent) {
    const ul = document.createElement('ul');

    for (const item of bodyContent) {
        const li = document.createElement('li');

        // Get highlight class
        const highlightType = item.highlight_type || 'none';
        li.className = getHighlightClass(highlightType);

        // If this is a definition (has a term), render term in bold
        if (item.term) {
            const termSpan = document.createElement('strong');
            termSpan.className = 'definition-term';
            termSpan.textContent = item.term;

            const separator = document.createTextNode(' — ');
            const descSpan = document.createElement('span');
            descSpan.textContent = item.text || '';

            li.appendChild(termSpan);
            li.appendChild(separator);
            li.appendChild(descSpan);
        } else {
            li.textContent = item.text || '';
        }

        ul.appendChild(li);
    }

    return ul;
}

/**
 * Render a single content item
 * @param {Object} item - Content item with text, highlight_type, and optional term
 * @returns {HTMLElement} List item element
 */
export function renderContentItem(item) {
    const li = document.createElement('li');
    const highlightType = item.highlight_type || 'none';
    li.className = getHighlightClass(highlightType);

    if (item.term) {
        const termSpan = document.createElement('strong');
        termSpan.className = 'definition-term';
        termSpan.textContent = item.term;

        const separator = document.createTextNode(' — ');
        const descSpan = document.createElement('span');
        descSpan.textContent = item.text || '';

        li.appendChild(termSpan);
        li.appendChild(separator);
        li.appendChild(descSpan);
    } else {
        li.textContent = item.text || '';
    }

    return li;
}
