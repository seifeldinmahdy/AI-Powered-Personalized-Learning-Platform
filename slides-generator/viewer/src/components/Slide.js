/**
 * Slide.js - Main slide component
 *
 * Renders slides with type-specific styling:
 * - Title: Large centered title, accent gradient
 * - Agenda: Numbered outline list
 * - Section: Full-width divider with section number
 * - Content: Standard layout with body + visual + code
 * - Summary: Key takeaways card
 */

import { getLayoutClass, getSlideTypeClass } from '../utils/parseSlide.js';
import { renderSlideTitle } from './SlideTitle.js';
import { renderSlideBody } from './SlideBody.js';
import { renderCodeBlock } from './CodeBlock.js';
import { renderVisual } from './visuals/VisualRenderer.js';

/**
 * Render a complete slide
 * @param {Object} slide - Slide data object
 * @param {Object} metadata - Optional metadata
 * @returns {HTMLElement} Slide element
 */
export function renderSlide(slide, metadata = null) {
    if (!slide) {
        return createEmptySlide();
    }

    const slideType = slide.slide_type || 'Content';
    const layoutClass = getLayoutClass(slide.layout);
    const typeClass = getSlideTypeClass(slideType);

    // Create slide container
    const slideEl = document.createElement('article');
    slideEl.className = `slide ${layoutClass} ${typeClass}`;

    // Slide number badge (top-right)
    if (slide.slide_number) {
        const numberBadge = document.createElement('div');
        numberBadge.className = 'slide-number-badge';
        numberBadge.textContent = slide.slide_number;
        slideEl.appendChild(numberBadge);
    }

    // Slide type badge (top-left)
    if (slideType !== 'Content') {
        const typeBadge = document.createElement('div');
        typeBadge.className = 'slide-type-badge';
        typeBadge.textContent = slideType;
        slideEl.appendChild(typeBadge);
    }

    // Add header with title
    const header = document.createElement('header');
    header.className = 'slide-header';
    header.appendChild(renderSlideTitle(slide.title));
    slideEl.appendChild(header);

    // Create content area
    const content = document.createElement('div');
    content.className = 'slide-content';

    // Add body content
    if (slide.body_content && slide.body_content.length > 0) {
        const body = document.createElement('div');
        body.className = 'slide-body';
        body.appendChild(renderSlideBody(slide.body_content));
        content.appendChild(body);
    }

    // Add visual if present
    if (slide.visual) {
        const visualContainer = document.createElement('div');
        visualContainer.className = 'slide-visual';
        visualContainer.appendChild(renderVisual(slide.visual));
        content.appendChild(visualContainer);
    }

    // Add code block if present
    if (slide.code_block) {
        const codeContainer = document.createElement('div');
        codeContainer.className = 'slide-code';
        codeContainer.appendChild(renderCodeBlock(slide.code_block));
        content.appendChild(codeContainer);
    }

    slideEl.appendChild(content);

    // Add alt text indicator if present (for accessibility mode)
    if (slide.alt_text) {
        const altIndicator = document.createElement('div');
        altIndicator.className = 'alt-text-indicator';
        altIndicator.textContent = slide.alt_text;
        slideEl.appendChild(altIndicator);
    }

    return slideEl;
}

/**
 * Create empty slide placeholder
 * @returns {HTMLElement} Empty slide element
 */
function createEmptySlide() {
    const slideEl = document.createElement('article');
    slideEl.className = 'slide layout-list-view';
    slideEl.innerHTML = `
        <header class="slide-header">
            <h2 class="slide-title">No Slide Data</h2>
        </header>
        <div class="slide-content">
            <div class="slide-body">
                <p style="color: var(--text-muted); text-align: center; padding: 2rem;">
                    Load a JSON or JSONL file to view slides
                </p>
            </div>
        </div>
    `;
    return slideEl;
}
