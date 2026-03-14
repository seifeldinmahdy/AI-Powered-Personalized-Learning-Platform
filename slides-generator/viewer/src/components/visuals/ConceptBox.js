/**
 * ConceptBox.js - Concept box visual template
 */

/**
 * Render a concept box with title and bullet points
 * @param {Object} params - { title, points }
 * @returns {HTMLElement} Concept box element
 */
export function renderConceptBox(params) {
    const container = document.createElement('div');
    container.className = 'visual-concept-box';

    // Title
    if (params.title) {
        const titleEl = document.createElement('div');
        titleEl.className = 'visual-title';
        titleEl.textContent = params.title;
        container.appendChild(titleEl);
    }

    // Points
    if (params.points && Array.isArray(params.points)) {
        const pointsList = document.createElement('ul');
        pointsList.className = 'visual-points';

        for (const point of params.points) {
            const li = document.createElement('li');

            // Handle both string and object points
            if (typeof point === 'string') {
                li.textContent = point;
            } else if (typeof point === 'object') {
                li.textContent = point.text || JSON.stringify(point);
            }

            pointsList.appendChild(li);
        }

        container.appendChild(pointsList);
    }

    // If no title or points, show params as content
    if (!params.title && (!params.points || params.points.length === 0)) {
        const content = document.createElement('div');
        content.className = 'visual-content';
        content.style.padding = '1rem';
        content.textContent = params.content || JSON.stringify(params);
        container.appendChild(content);
    }

    return container;
}
