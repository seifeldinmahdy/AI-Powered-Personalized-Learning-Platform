/**
 * loadData.js - Load and parse slide data from JSONL training files or deck JSON
 */

/**
 * Load JSONL file from file input
 * @param {File} file - File object from input
 * @returns {Promise<Array>} Array of training examples
 */
export async function loadJSONLFile(file) {
    const text = await file.text();
    return parseJSONL(text);
}

/**
 * Load a JSON file (deck array)
 * @param {File} file - File object from input
 * @returns {Promise<Array>} Array of slide objects
 */
export async function loadJSONFile(file) {
    const text = await file.text();
    try {
        const data = JSON.parse(text);
        if (Array.isArray(data)) {
            return data;
        }
        return [data];
    } catch (e) {
        console.error('Failed to parse JSON file:', e);
        return [];
    }
}

/**
 * Parse JSONL string into array of objects
 * @param {string} text - JSONL content
 * @returns {Array} Parsed objects
 */
export function parseJSONL(text) {
    const lines = text.trim().split('\n');
    const results = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;

        try {
            const obj = JSON.parse(line);
            results.push(obj);
        } catch (e) {
            console.warn(`Failed to parse line ${i + 1}:`, e);
        }
    }

    return results;
}

/**
 * Detect if a file contains deck JSON (array of SlideInstructions)
 * vs JSONL training data (input/target pairs)
 * @param {string} filename - File name
 * @param {Array} data - Parsed data
 * @returns {'deck'|'training'} Data format type
 */
export function detectDataFormat(filename, data) {
    // Check file extension first
    if (filename.endsWith('.json')) return 'deck';
    if (filename.endsWith('.jsonl')) return 'training';

    // Inspect first item
    if (data.length > 0) {
        const first = data[0];
        // Deck slides have slide_type, layout, title
        if (first.slide_type || first.layout || (first.title && first.body_content)) {
            return 'deck';
        }
        // Training data has input/target
        if (first.input && first.target) {
            return 'training';
        }
    }

    return 'training'; // Default
}

/**
 * Load sample data for testing - includes deck-format slides
 * @returns {Array} Sample deck slides
 */
export function getSampleData() {
    return [
        {
            slide_type: 'Title',
            slide_number: 1,
            layout: 'Content_Visual',
            title: 'Introduction to Python Programming',
            body_content: [],
            visual: null,
            code_block: null,
            alt_text: null
        },
        {
            slide_type: 'Agenda',
            slide_number: 2,
            layout: 'List_View',
            title: 'What We\'ll Cover',
            body_content: [
                { text: 'Variables & Data Types', highlight_type: 'none', term: null },
                { text: 'Control Flow', highlight_type: 'none', term: null },
                { text: 'Functions & Modules', highlight_type: 'none', term: null }
            ],
            visual: null,
            code_block: null,
            alt_text: null
        },
        {
            slide_type: 'Section',
            slide_number: 3,
            layout: 'Content_Visual',
            title: 'Variables & Data Types',
            body_content: [
                { text: 'Section 1 of 3', highlight_type: 'none', term: null }
            ],
            visual: null,
            code_block: null,
            alt_text: null
        },
        {
            slide_type: 'Content',
            slide_number: 4,
            layout: 'Content_Visual',
            title: 'Understanding Variables',
            body_content: [
                { text: 'A variable is a named location in memory that stores a value.', highlight_type: 'definition', term: 'Variable' },
                { text: 'Variables are created when you first assign a value to them using the = operator.', highlight_type: 'key_concept', term: null },
                { text: 'For example: name = "Alice" creates a string variable.', highlight_type: 'example', term: null }
            ],
            visual: {
                template: 'concept_box',
                params: {
                    title: 'Variable Types',
                    points: ['int — whole numbers', 'float — decimal numbers', 'str — text strings', 'bool — True/False']
                }
            },
            code_block: null,
            alt_text: null
        },
        {
            slide_type: 'Content',
            slide_number: 5,
            layout: 'Code_Main',
            title: 'Working with Variables',
            body_content: [
                { text: 'Python uses dynamic typing — the type is inferred from the value.', highlight_type: 'key_concept', term: null },
                { text: 'You can check a variable\'s type using the type() function.', highlight_type: 'example', term: null }
            ],
            visual: null,
            code_block: {
                language: 'python',
                code: 'name = "Alice"\nage = 25\nheight = 5.6\nis_student = True\n\nprint(type(name))    # <class \'str\'>\nprint(type(age))     # <class \'int\'>'
            },
            alt_text: null
        },
        {
            slide_type: 'Summary',
            slide_number: 6,
            layout: 'List_View',
            title: 'Key Takeaways: Variables & Data Types',
            body_content: [
                { text: 'Variables store values and are created on first assignment.', highlight_type: 'key_concept', term: null },
                { text: 'Python has four main data types: int, float, str, and bool.', highlight_type: 'key_concept', term: null },
                { text: 'Dynamic typing means you don\'t declare types explicitly.', highlight_type: 'key_concept', term: null }
            ],
            visual: null,
            code_block: null,
            alt_text: null
        }
    ];
}
