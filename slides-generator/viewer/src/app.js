/**
 * app.js - Main application entry point
 *
 * Supports two data formats:
 * 1. Deck JSON (.json) — array of SlideInstruction objects from the pipeline
 * 2. Training JSONL (.jsonl) — input/target pairs from training data
 */

import { renderSlide } from './components/Slide.js';
import { loadJSONLFile, loadJSONFile, getSampleData, detectDataFormat } from './utils/loadData.js';
import { parseTrainingExample, parseDeckSlide } from './utils/parseSlide.js';

// Application State
const state = {
    slides: [],
    currentIndex: 0,
    metadata: [],
    format: 'deck'  // 'deck' or 'training'
};

// DOM Elements
const elements = {
    app: document.getElementById('app'),
    slideWrapper: document.getElementById('slide-wrapper'),
    prevBtn: document.getElementById('prev-btn'),
    nextBtn: document.getElementById('next-btn'),
    currentSlideEl: document.getElementById('current-slide'),
    totalSlidesEl: document.getElementById('total-slides'),
    fileInput: document.getElementById('file-input')
};

/**
 * Initialize application
 */
function init() {
    // Event listeners
    elements.prevBtn.addEventListener('click', prevSlide);
    elements.nextBtn.addEventListener('click', nextSlide);
    elements.fileInput.addEventListener('change', handleFileLoad);

    // Keyboard navigation
    document.addEventListener('keydown', handleKeyNavigation);

    // Load sample data initially
    loadSampleData();
}

/**
 * Handle file input change — auto-detect JSON vs JSONL
 */
async function handleFileLoad(event) {
    const file = event.target.files[0];
    if (!file) return;

    try {
        let data;
        const filename = file.name.toLowerCase();

        // Load based on file extension
        if (filename.endsWith('.json')) {
            data = await loadJSONFile(file);
        } else {
            data = await loadJSONLFile(file);
        }

        if (!data || data.length === 0) {
            alert('No valid data found in file.');
            return;
        }

        // Auto-detect format
        const format = detectDataFormat(filename, data);
        state.format = format;

        if (format === 'deck') {
            // Deck JSON: slides are already in SlideInstruction format
            const processed = data.map(item => parseDeckSlide(item));
            state.slides = processed.map(p => p.slide).filter(s => s !== null);
            state.metadata = processed.map(p => p.metadata);
        } else {
            // Training JSONL: parse input/target pairs
            const processed = data.map(item => parseTrainingExample(item));
            state.slides = processed.map(p => p.slide).filter(s => s !== null);
            state.metadata = processed.map(p => p.metadata);
        }

        state.currentIndex = 0;
        updateUI();

        // Reset file input so same file can be loaded again
        event.target.value = '';

        console.log(`Loaded ${state.slides.length} slides (format: ${format})`);
    } catch (error) {
        console.error('Error loading file:', error);
        alert('Error loading file. Check console for details.');
    }
}

/**
 * Load sample data for demonstration
 */
function loadSampleData() {
    const data = getSampleData();
    const processed = data.map(item => parseDeckSlide(item));

    state.slides = processed.map(p => p.slide);
    state.metadata = processed.map(p => p.metadata);
    state.format = 'deck';
    state.currentIndex = 0;

    updateUI();
}

/**
 * Update the UI with current slide
 */
function updateUI() {
    // Update counter
    elements.currentSlideEl.textContent = state.currentIndex + 1;
    elements.totalSlidesEl.textContent = state.slides.length;

    // Update button states
    elements.prevBtn.disabled = state.currentIndex === 0;
    elements.nextBtn.disabled = state.currentIndex === state.slides.length - 1;

    // Render current slide
    const currentSlide = state.slides[state.currentIndex];
    const currentMetadata = state.metadata[state.currentIndex];

    elements.slideWrapper.innerHTML = '';

    if (currentSlide) {
        const slideEl = renderSlide(currentSlide, currentMetadata);
        elements.slideWrapper.appendChild(slideEl);
    }
}

/**
 * Go to previous slide
 */
function prevSlide() {
    if (state.currentIndex > 0) {
        state.currentIndex--;
        updateUI();
    }
}

/**
 * Go to next slide
 */
function nextSlide() {
    if (state.currentIndex < state.slides.length - 1) {
        state.currentIndex++;
        updateUI();
    }
}

/**
 * Handle keyboard navigation
 */
function handleKeyNavigation(event) {
    if (event.key === 'ArrowLeft') {
        prevSlide();
    } else if (event.key === 'ArrowRight') {
        nextSlide();
    }
}

// Start app
init();
