/**
 * Comparison.js - Side-by-side comparison visual template
 */

/**
 * Render a comparison visual with left and right sides
 * @param {Object} params - { left_items, right_items, left_label, right_label }
 * @returns {HTMLElement} Comparison element
 */
export function renderComparison(params) {
    const container = document.createElement('div');
    container.className = 'visual-comparison';

    // Left side
    const leftSide = document.createElement('div');
    leftSide.className = 'comparison-side comparison-left';

    const leftLabel = document.createElement('div');
    leftLabel.className = 'comparison-label';
    leftLabel.textContent = params.left_label || 'Option A';
    leftSide.appendChild(leftLabel);

    if (params.left_items && Array.isArray(params.left_items)) {
        const leftList = document.createElement('ul');
        leftList.className = 'comparison-items';

        for (const item of params.left_items) {
            const li = document.createElement('li');
            li.textContent = typeof item === 'string' ? item : item.text || JSON.stringify(item);
            leftList.appendChild(li);
        }
        leftSide.appendChild(leftList);
    }

    container.appendChild(leftSide);

    // Right side
    const rightSide = document.createElement('div');
    rightSide.className = 'comparison-side comparison-right';

    const rightLabel = document.createElement('div');
    rightLabel.className = 'comparison-label';
    rightLabel.textContent = params.right_label || 'Option B';
    rightSide.appendChild(rightLabel);

    if (params.right_items && Array.isArray(params.right_items)) {
        const rightList = document.createElement('ul');
        rightList.className = 'comparison-items';

        for (const item of params.right_items) {
            const li = document.createElement('li');
            li.textContent = typeof item === 'string' ? item : item.text || JSON.stringify(item);
            rightList.appendChild(li);
        }
        rightSide.appendChild(rightList);
    }

    container.appendChild(rightSide);

    return container;
}
