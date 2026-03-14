/**
 * SlideBody.js - Body content component with highlight types
 */

import { getHighlightClass } from '../utils/parseSlide.js';

/**
 * Render slide body content (bullet points)
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

        // Set text content
        li.textContent = item.text || '';

        ul.appendChild(li);
    }

    return ul;
}

/**
 * Render a single content item
 * @param {Object} item - Content item with text and highlight_type
 * @returns {HTMLElement} List item element
 */
export function renderContentItem(item) {
    const li = document.createElement('li');
    const highlightType = item.highlight_type || 'none';
    li.className = getHighlightClass(highlightType);
    li.textContent = item.text || '';
    return li;
}
