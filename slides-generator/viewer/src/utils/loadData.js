/**
 * loadData.js - Load and parse JSONL training data
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
 * Load sample data for testing
 * @returns {Array} Sample training examples
 */
export function getSampleData() {
    return [
        {
            input: "[MASTERY: Novice] [MODE: Visual_Heavy] [LANG: Elementary] [A11Y: False]\nContext: Sample content about Python basics",
            target: JSON.stringify({
                layout: "Content_Visual",
                title: "Getting Started with Python",
                body_content: [
                    { text: "Python is a beginner-friendly programming language.", highlight_type: "definition" },
                    { text: "It uses simple, readable syntax.", highlight_type: "example" }
                ],
                visual: {
                    template: "concept_box",
                    params: {
                        title: "Why Python?",
                        points: [
                            "Easy to learn",
                            "Readable code",
                            "Large community"
                        ]
                    }
                },
                code_block: null,
                alt_text: null
            })
        },
        {
            input: "[MASTERY: Expert] [MODE: Code_Main] [LANG: Advanced] [A11Y: True]\nContext: Advanced Python decorators",
            target: JSON.stringify({
                layout: "Code_Main",
                title: "Python Decorators",
                body_content: [
                    { text: "Decorators modify function behavior without changing code.", highlight_type: "definition" },
                    { text: "Use @decorator syntax to apply.", highlight_type: "key_concept" }
                ],
                visual: null,
                code_block: {
                    language: "python",
                    code: "def my_decorator(func):\n    def wrapper(*args):\n        print('Before call')\n        result = func(*args)\n        print('After call')\n        return result\n    return wrapper\n\n@my_decorator\ndef greet(name):\n    print(f'Hello, {name}!')"
                },
                alt_text: "A Python decorator example showing a wrapper function"
            })
        }
    ];
}
