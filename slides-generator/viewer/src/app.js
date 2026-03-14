/**
 * app.js - Main application entry point
 */

import { renderSlide } from './components/Slide.js';
import { loadJSONLFile, getSampleData } from './utils/loadData.js';
import { parseTrainingExample } from './utils/parseSlide.js';

// Application State
const state = {
    slides: [],
    currentIndex: 0,
    metadata: []
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

    // Load sample data initially if no file selected
    loadSampleData();
}

/**
 * Handle file input change
 */
async function handleFileLoad(event) {
    const file = event.target.files[0];
    if (!file) return;

    try {
        const data = await loadJSONLFile(file);

        if (data && data.length > 0) {
            // Process data to extract slides and metadata
            const processed = data.map(item => parseTrainingExample(item));

            state.slides = processed.map(p => p.slide).filter(s => s !== null);
            state.metadata = processed.map(p => p.metadata);
            state.currentIndex = 0;

            updateUI();

            // Reset file input so same file can be loaded again
            event.target.value = '';
        } else {
            alert('No valid JSON data found in file.');
        }
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
    const processed = data.map(item => parseTrainingExample(item));

    state.slides = processed.map(p => p.slide);
    state.metadata = processed.map(p => p.metadata);
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

        // Console log for debugging context
        console.log('Current Slide:', currentSlide);
        console.log('Metadata:', currentMetadata);
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
