# AI-Powered Slide Generator

A synthetic data generation pipeline for training T5 models to generate personalized slide instructions from textbook content.

## Project Structure

```
slides-generator/
├── config/
│   └── prompts.yaml            # Teacher LLM system prompts
├── data/
│   ├── raw_books/              # Place PDF files here
│   └── synthetic/              # Generated .jsonl output
├── src/
│   └── slide_gen/
│       ├── core/               # Pydantic Schemas
│       │   ├── profile_schema.py   # StudentProfile definitions
│       │   └── slide_schema.py     # Slide JSON Output definitions
│       └── data_engine/        # Data Generation Logic
│           ├── pdf_loader.py       # PDF loading utilities
│           └── factory.py          # Main generation factory
├── scripts/
│   └── generate_dataset.py     # Entry point
├── .env                        # Configuration
└── pyproject.toml              # Project metadata
```

## Setup

1. **Create virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -e .
   ```

3. **Install Ollama and pull a model:**
   ```bash
   # Install Ollama from https://ollama.ai
   ollama pull llama3  # or mistral
   ```

4. **Place your PDF:**
   Copy "Think Python 2nd Edition.pdf" (or your PDF) to `data/raw_books/`

## Usage

Run the data generation:

```bash
python scripts/generate_dataset.py
```

## Configuration

Edit `.env` to customize:

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
PROFILES_PER_CHUNK=3
MAX_RETRIES=3
```

## Output Format

The generated `training_data.jsonl` contains entries like:

```json
{
  "input": "CONTEXT: <chunk text> | PROFILE: mastery_level=Novice | ...",
  "target": "{\"layout\": \"Content_Visual\", \"title\": \"...\", ...}"
}
```

## Student Profile Options

- **Mastery Level:** Novice, Intermediate, Expert
- **Composition Mode:** Visual_Heavy, Text_Heavy, Balanced
- **Language Proficiency:** Elementary, Intermediate, Advanced, Native
- **Target Goal:** Job_Interview, Academic_Exam, Hobby_Project
- **Interest Domain:** Game_Dev, Web_Development, Data_Science, Robotics, Finance
- **Prior Context:** Java_Dev, C++_Dev, Excel_User, None
