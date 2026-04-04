/**
 * parseSlide.js - Parse slide data from training data or deck JSON
 */

/**
 * Parse a slide object from the training data target
 * @param {Object|string} target - The target field from training data
 * @returns {Object} Parsed slide object
 */
export function parseSlide(target) {
    if (typeof target === 'object' && target !== null) {
        return target;
    }

    if (typeof target === 'string') {
        try {
            return JSON.parse(target);
        } catch (e) {
            console.error('Failed to parse slide JSON:', e);
            return null;
        }
    }

    return null;
}

/**
 * Parse a training example (input/target pair) into a slide
 * @param {Object} example - Training example with input and target
 * @returns {Object} Parsed example with slide data and metadata
 */
export function parseTrainingExample(example) {
    const slide = parseSlide(example.target);
    const metadata = parseInputMetadata(example.input);

    return {
        slide,
        metadata,
        raw: example
    };
}

/**
 * Parse a deck slide — already in SlideInstruction format
 * @param {Object} slide - A slide from deck JSON
 * @returns {Object} The same slide (already in correct format)
 */
export function parseDeckSlide(slide) {
    return {
        slide: slide,
        metadata: {
            slideType: slide.slide_type || 'Content',
            slideNumber: slide.slide_number || null,
            mastery: null,
            mode: null,
            language: null,
            a11y: false,
            context: ''
        },
        raw: slide
    };
}

/**
 * Parse metadata from input string
 * @param {string} input - The input string with [TAGS]
 * @returns {Object} Parsed metadata
 */
export function parseInputMetadata(input) {
    const metadata = {
        slideType: 'Content',
        slideNumber: null,
        mastery: null,
        mode: null,
        language: null,
        a11y: false,
        context: ''
    };

    // Extract tags using regex
    const masteryMatch = input.match(/\[MASTERY:\s*(\w+)\]/);
    const modeMatch = input.match(/\[MODE:\s*(\w+)\]/);
    const langMatch = input.match(/\[LANG:\s*(\w+)\]/);
    const a11yMatch = input.match(/\[A11Y:\s*(\w+)\]/);

    if (masteryMatch) metadata.mastery = masteryMatch[1];
    if (modeMatch) metadata.mode = modeMatch[1];
    if (langMatch) metadata.language = langMatch[1];
    if (a11yMatch) metadata.a11y = a11yMatch[1].toLowerCase() === 'true';

    // Extract context (everything after "Context:")
    const contextMatch = input.match(/Context:\s*([\s\S]*)/);
    if (contextMatch) metadata.context = contextMatch[1].trim();

    return metadata;
}

/**
 * Get layout CSS class from layout value
 * @param {string} layout - Layout type
 * @returns {string} CSS class
 */
export function getLayoutClass(layout) {
    const layoutMap = {
        'Content_Visual': 'layout-content-visual',
        'List_View': 'layout-list-view',
        'Code_Main': 'layout-code-main'
    };
    return layoutMap[layout] || 'layout-content-visual';
}

/**
 * Get slide type CSS class
 * @param {string} slideType - Slide type (Title, Agenda, Section, Content, Summary)
 * @returns {string} CSS class
 */
export function getSlideTypeClass(slideType) {
    const typeMap = {
        'Title': 'slide-type-title',
        'Agenda': 'slide-type-agenda',
        'Section': 'slide-type-section',
        'Content': 'slide-type-content',
        'Summary': 'slide-type-summary'
    };
    return typeMap[slideType] || 'slide-type-content';
}

/**
 * Get highlight CSS class from highlight type
 * @param {string} highlightType - Highlight type
 * @returns {string} CSS class
 */
export function getHighlightClass(highlightType) {
    const validTypes = ['none', 'definition', 'example', 'key_concept', 'attention', 'code'];
    const type = validTypes.includes(highlightType) ? highlightType : 'none';
    return `highlight-${type}`;
}
