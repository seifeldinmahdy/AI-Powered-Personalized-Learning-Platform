/**
 * Slide.js - Main slide component
 */

import { getLayoutClass } from '../utils/parseSlide.js';
import { renderSlideTitle } from './SlideTitle.js';
import { renderSlideBody } from './SlideBody.js';
import { renderCodeBlock } from './CodeBlock.js';
import { renderVisual } from './visuals/VisualRenderer.js';

/**
 * Render a complete slide
 * @param {Object} slide - Slide data object
 * @param {Object} metadata - Optional metadata from input
 * @returns {HTMLElement} Slide element
 */
export function renderSlide(slide, metadata = null) {
    if (!slide) {
        return createEmptySlide();
    }

    const layoutClass = getLayoutClass(slide.layout);

    // Create slide container
    const slideEl = document.createElement('article');
    slideEl.className = `slide ${layoutClass}`;

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
                    Load a JSONL file to view slides
                </p>
            </div>
        </div>
    `;
    return slideEl;
}
