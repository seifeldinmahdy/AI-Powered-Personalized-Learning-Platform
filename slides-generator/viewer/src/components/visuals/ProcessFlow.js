/**
 * ProcessFlow.js - Horizontal process flow visual template
 */

/**
 * Render a process flow with connected steps
 * @param {Object} params - { steps } or { items }
 * @returns {HTMLElement} Process flow element
 */
export function renderProcessFlow(params) {
    const container = document.createElement('div');
    container.className = 'visual-process-flow';

    // Get steps from various possible param keys
    const steps = params.steps || params.items || params.points || [];

    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];

        // Step container
        const stepEl = document.createElement('div');
        stepEl.className = 'flow-step';

        // Step box
        const stepBox = document.createElement('div');
        stepBox.className = 'flow-step-box';
        stepBox.textContent = typeof step === 'string' ? step : step.label || step.text || JSON.stringify(step);
        stepEl.appendChild(stepBox);

        container.appendChild(stepEl);

        // Add arrow between steps (not after last)
        if (i < steps.length - 1) {
            const arrow = document.createElement('span');
            arrow.className = 'flow-arrow';
            arrow.textContent = '→';
            container.appendChild(arrow);
        }
    }

    // If no steps, show placeholder
    if (steps.length === 0) {
        container.textContent = 'No flow steps defined';
        container.style.color = 'var(--text-muted)';
    }

    return container;
}
