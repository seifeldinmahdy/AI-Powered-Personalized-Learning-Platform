/**
 * SlideTitle.js - Slide title component
 */

/**
 * Render slide title
 * @param {string} title - Title text
 * @returns {HTMLElement} Title element
 */
export function renderSlideTitle(title) {
    const titleEl = document.createElement('h2');
    titleEl.className = 'slide-title';
    titleEl.textContent = title || 'Untitled Slide';
    return titleEl;
}
