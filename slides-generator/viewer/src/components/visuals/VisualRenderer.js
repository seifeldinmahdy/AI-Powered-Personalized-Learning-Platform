/**
 * VisualRenderer.js - Router for visual template rendering
 */

import { renderConceptBox } from './ConceptBox.js';
import { renderComparison } from './Comparison.js';
import { renderProcessFlow } from './ProcessFlow.js';
import { renderStack } from './Stack.js';

/**
 * Render a visual based on template type
 * @param {Object} visual - Visual object with template and params
 * @returns {HTMLElement} Rendered visual element
 */
export function renderVisual(visual) {
    if (!visual || !visual.template) {
        return createEmptyVisual();
    }

    const template = visual.template;
    const params = visual.params || {};

    // Route to specific renderer based on template
    switch (template) {
        case 'concept_box':
            return renderConceptBox(params);

        case 'info_card':
        case 'definition_box':
            return renderConceptBox(params); // Same renderer, different styling via CSS

        case 'comparison':
            return renderComparison(params);

        case 'process_flow':
        case 'timeline':
            return renderProcessFlow(params);

        case 'stack':
            return renderStack(params);

        case 'queue':
            return renderStack(params); // Similar to stack

        // Generic fallback for unimplemented templates
        default:
            return renderGenericVisual(template, params);
    }
}

/**
 * Create empty visual placeholder
 * @returns {HTMLElement} Empty visual element
 */
function createEmptyVisual() {
    const container = document.createElement('div');
    container.className = 'visual-generic';
    container.innerHTML = '<p>No visual data</p>';
    return container;
}

/**
 * Generic visual for unimplemented templates
 * @param {string} template - Template name
 * @param {Object} params - Template parameters
 * @returns {HTMLElement} Generic visual element
 */
function renderGenericVisual(template, params) {
    const container = document.createElement('div');
    container.className = 'visual-generic';

    const templateName = document.createElement('div');
    templateName.className = 'template-name';
    templateName.textContent = template;
    container.appendChild(templateName);

    // If params has common fields, display them
    if (params.title) {
        const title = document.createElement('div');
        title.style.fontWeight = '600';
        title.style.marginTop = '0.5rem';
        title.textContent = params.title;
        container.appendChild(title);
    }

    if (params.points && Array.isArray(params.points)) {
        const list = document.createElement('ul');
        list.style.textAlign = 'left';
        list.style.marginTop = '0.5rem';
        list.style.paddingLeft = '1.5rem';

        for (const point of params.points) {
            const li = document.createElement('li');
            li.textContent = typeof point === 'string' ? point : JSON.stringify(point);
            list.appendChild(li);
        }
        container.appendChild(list);
    }

    return container;
}
