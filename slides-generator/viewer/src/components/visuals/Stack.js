/**
 * Stack.js - Vertical stack visual template
 */

/**
 * Render a stack visualization
 * @param {Object} params - { items, top_label }
 * @returns {HTMLElement} Stack element
 */
export function renderStack(params) {
    const container = document.createElement('div');
    container.className = 'visual-stack';

    // Get items from various possible param keys
    const items = params.items || params.elements || params.points || [];

    // Render items (top to bottom = first item is top of stack)
    for (const item of items) {
        const itemEl = document.createElement('div');
        itemEl.className = 'stack-item';
        itemEl.textContent = typeof item === 'string' ? item : item.value || item.text || JSON.stringify(item);
        container.appendChild(itemEl);
    }

    // Add label if provided
    if (params.top_label || params.label) {
        const label = document.createElement('div');
        label.className = 'stack-label';
        label.textContent = `↑ ${params.top_label || params.label}`;
        container.appendChild(label);
    }

    // If no items, show placeholder
    if (items.length === 0) {
        const placeholder = document.createElement('div');
        placeholder.className = 'stack-item';
        placeholder.textContent = 'Empty stack';
        placeholder.style.color = 'var(--text-muted)';
        container.appendChild(placeholder);
    }

    return container;
}
