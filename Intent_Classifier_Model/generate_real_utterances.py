"""
Generate a real-utterance test set using the Groq API (cloud LLM).

Produces `data/real_utterances_test.csv` with 200+ annotated samples (40+ per class)
in the standard schema: student_input, session_context, label, intent_name.

Uses `llama-3.3-70b-versatile` on Groq's cloud — no local GPU required.

Usage:
    python generate_real_utterances.py                # Generate all classes
    python generate_real_utterances.py --per-class 50 # 50 per class instead of 40
"""

import argparse
import json
import os
import random
import time
import logging

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ─────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────

LABEL_MAP = {
    'On-Topic Question': 0,
    'Off-Topic Question': 1,
    'Emotional-State': 2,
    'Pace-Related': 3,
    'Repeat/clarification': 4,
}

PYTHON_TOPICS = [
    "Variables and Data Types", "Strings and Formatting", "Arithmetic Operators",
    "Boolean Logic", "If/Else Conditionals", "For Loops", "While Loops",
    "Lists and Tuples", "Dictionaries", "Sets", "Functions and Scope",
    "Lambda Functions", "Error Handling (Try/Except)", "Classes and OOP", "File Handling",
]

EMOTIONS = ["neutral", "engaged", "focused", "frustrated", "confused", "bored",
            "tired", "anxious", "excited", "overwhelmed"]
PACES = ["normal", "fast", "slow", "rushed", "dragging", "moderate", "steady"]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'data', 'real_utterances.csv')
CACHE_PATH  = os.path.join(os.path.dirname(__file__), 'data', 'real_utterances_cache.json')

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RAG_PIPELINE_DIR = os.path.abspath(os.path.join(_THIS_DIR, '..', 'rag_pipeline'))

MODEL = "llama-3.3-70b-versatile"

# ─────────────────────────────────────────────────────────────────────
# CLASS DEFINITIONS & FEW-SHOT EXAMPLES
# ─────────────────────────────────────────────────────────────────────

CLASS_DEFINITIONS = {
    'On-Topic Question': {
        'definition': (
            "The student is asking about the current Python topic being taught. "
            "They want an explanation, example, clarification, or help debugging code. "
            "Signal words: 'how', 'why', 'what', 'show me', 'explain', 'example', 'difference', 'error'."
        ),
        'examples': [
            "how do i make a for loop work with a dictionary",
            "yo can u show me how to do list comprehension",
            "why does my function keep returning None bro",
            "whats the diff between == and is",
            "i keep getting index out of range error help",
            "can u explain the difference between args and kwargs",
            "what does self mean in a class",
            "how do i read a file line by line",
        ],
    },
    'Off-Topic Question': {
        'definition': (
            "The student is talking about something completely unrelated to the "
            "current lesson or programming in general. They might be asking about "
            "entertainment, food, social media, personal life, etc."
        ),
        'examples': [
            "whats the best anime rn",
            "do u think pineapple belongs on pizza",
            "who won the champions league",
            "can u help me with my resume",
            "how do i get more followers on tiktok",
            "tell me a fun fact",
            "how much does a software engineer make",
            "when is spring break",
        ],
    },
    'Emotional-State': {
        'definition': (
            "The student is expressing a feeling or emotional state — frustration, "
            "confusion, excitement, boredom, tiredness, anxiety, etc. They are NOT "
            "asking a technical question; they are sharing how they feel."
        ),
        'examples': [
            "bruh this is impossible",
            "lmaooo im so lost rn",
            "ngl im kinda vibing with this",
            "dawg im cooked fr",
            "i wanna cry rn",
            "omg i finally get it",
            "im lowkey stressed about this exam",
            "this aint it chief",
        ],
    },
    'Pace-Related': {
        'definition': (
            "The student wants to change the speed/pace of the lesson — slow down, "
            "speed up, skip ahead, take a break, or ask about remaining content. "
            "Signal words: 'slow', 'fast', 'skip', 'next', 'break', 'pace', 'hurry'."
        ),
        'examples': [
            "yo can we slow down a bit",
            "bro ur going way too fast",
            "can we just skip this part",
            "next slide pls",
            "hold on lemme think for a sec",
            "i already know this lets move on",
            "lets speed this up im bored",
            "how many slides left",
        ],
    },
    'Repeat/clarification': {
        'definition': (
            "The student wants the tutor to repeat, re-explain, or go back to "
            "something that was just said. They missed it, didn't hear it, or "
            "want it explained again."
        ),
        'examples': [
            "wait what did u just say",
            "can u say that again i wasnt listening",
            "huh",
            "sorry i zoned out can u repeat",
            "go back to the last slide real quick",
            "i didnt get that last part at all",
            "explain that one more time pls",
            "come again??",
        ],
    },
}

# DDAIR: adjacent class definitions for boundary-aware generation
# The model generates better utterances when it knows what the confused classes look like.
ADJACENT_CLASSES = {
    'On-Topic Question': ['Off-Topic Question'],
    'Off-Topic Question': ['On-Topic Question'],
    'Pace-Related': ['Repeat/clarification'],
    'Repeat/clarification': ['Pace-Related'],
    'Emotional-State': [],  # no dominant confusion pair
}


# ─────────────────────────────────────────────────────────────────────
# RAG PASSAGE FETCHER
# ─────────────────────────────────────────────────────────────────────


def _fetch_rag_passages_for_topic(topic: str, top_k: int = 4) -> list[str]:
    """Fetch real textbook passages from ChromaDB for a topic.
    Returns empty list if RAG pipeline unavailable — generation falls back silently.
    """
    import sys
    if _RAG_PIPELINE_DIR not in sys.path:
        sys.path.insert(0, _RAG_PIPELINE_DIR)
    try:
        original_cwd = os.getcwd()
        os.chdir(_RAG_PIPELINE_DIR)
        from src.config.settings import get_settings
        from src.llm.client import OllamaCloudClient
        from src.retrieval.engine import RAGEngine
        settings = get_settings()
        os.chdir(original_cwd)
        settings.chroma_db_path = os.path.join(_RAG_PIPELINE_DIR, 'data', 'chroma')
        llm_client = OllamaCloudClient(
            host=settings.ollama_host, model=settings.ollama_model,
            api_key=settings.ollama_api_key, max_retries=settings.max_retries,
        )
        engine = RAGEngine(settings=settings, llm_client=llm_client)
        response = engine.ask(
            question=f'Explain {topic} in Python with examples',
            topic=topic, top_k=top_k,
        )
        passages = []
        if response and response.sources:
            for s in response.sources:
                raw = getattr(s, 'text', '') or ''
                if len(raw) > 40:
                    passages.append(raw.strip())
        logger.info('RAG: %d passages for topic "%s"', len(passages), topic)
        return passages
    except Exception as exc:
        logger.warning('RAG fetch failed for "%s": %s — template-only fallback', topic, exc)
        return []


def _format_rag_block(passages: list[str], topic: str) -> str:
    if not passages:
        return ''
    lines = [
        f'\n**Real textbook excerpts about {topic}**',
        'Generate at least 10 questions that reference SPECIFIC concepts, code patterns,',
        'or examples from these excerpts — not generic questions.\n',
    ]
    for i, p in enumerate(passages[:3], 1):
        snippet = p[:400].replace('\n', ' ')
        if len(p) > 400:
            snippet += '...'
        lines.append(f'[Excerpt {i}]: {snippet}\n')
    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────
# CONTEXT GENERATION
# ─────────────────────────────────────────────────────────────────────

def generate_random_context() -> str:
    """Generate a realistic session context string."""
    topic_idx = random.randint(0, len(PYTHON_TOPICS) - 1)
    topic = PYTHON_TOPICS[topic_idx]
    prev = PYTHON_TOPICS[topic_idx - 1] if topic_idx > 0 else "None"
    emotion = random.choice(EMOTIONS)
    pace = random.choice(PACES)
    slide = random.randint(3, 50)
    return (
        f"topic:{topic} | prev:{prev} | ability:N/A | "
        f"emotion:{emotion} | pace:{pace} | slides:{slide},{slide+1},{slide+2}"
    )


# ─────────────────────────────────────────────────────────────────────
# GROQ API GENERATION
# ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def generate_utterances_for_class(
    client,
    intent_name: str,
    n_utterances: int = 40,
    cache: dict | None = None,
    rag_passages: list[str] | None = None,
) -> list[str]:
    """
    Use Groq to generate realistic student utterances for a given intent class.
    Returns a list of utterance strings.
    """
    cache_key = f"{intent_name}_{n_utterances}_{'rag' if rag_passages else 'norag'}"
    if cache and cache_key in cache:
        logger.info(f"  Cache hit for {intent_name} ({len(cache[cache_key])} utterances)")
        return cache[cache_key]

    class_info = CLASS_DEFINITIONS[intent_name]
    examples_str = '\n'.join(f'  - "{ex}"' for ex in class_info['examples'])

    # Build adjacent-class boundary context (DDAIR approach)
    adjacent_names = ADJACENT_CLASSES.get(intent_name, [])
    adjacent_block = ""
    if adjacent_names:
        adj_lines = []
        for adj_name in adjacent_names:
            adj_info = CLASS_DEFINITIONS[adj_name]
            adj_lines.append(f'- "{adj_name}": {adj_info["definition"]}')
        adjacent_block = (
            "\n\n**Adjacent class(es) to AVOID** (do NOT generate utterances that could fit these):\n"
            + "\n".join(adj_lines)
            + "\nMake sure every utterance you generate is clearly distinguishable from the adjacent class(es) above."
        )

    rag_block = ''
    if rag_passages and intent_name == 'On-Topic Question':
        rag_block = _format_rag_block(rag_passages, 'the current Python topic')

    prompt = f"""You are a data generation expert for an educational AI tutor system.

Generate exactly {n_utterances} realistic student utterances for the intent class: "{intent_name}"

**Class definition**: {class_info['definition']}

**Example utterances** (for reference style, do NOT copy these):
{examples_str}
{rag_block}
**Requirements**:
1. Each utterance must be something a REAL college student would type in a chat
2. Vary the style: formal, casual, slang, Gen-Z speak, typos, abbreviations, ALL CAPS
3. Vary the length: some 1-2 words, some full sentences, some with punctuation quirks
4. Include at least 5 utterances with deliberate typos or misspellings
5. Include at least 5 ultra-short utterances (1-3 words)
6. Do NOT include any utterances that could plausibly belong to a different class
7. Do NOT copy the example utterances — generate completely new ones
8. For On-Topic: reference specific Python concepts (variables, loops, functions, etc.)
9. For Off-Topic: reference real-world topics unrelated to programming{adjacent_block}

Return ONLY a JSON object in this exact format:
{{"utterances": ["utterance1", "utterance2", ...]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.9,
            max_tokens=4096,
            response_format={'type': 'json_object'},
        )
        text = resp.choices[0].message.content.strip()
        data = json.loads(text)
        utterances = data.get('utterances', [])

        if len(utterances) < n_utterances * 0.8:
            logger.warning(
                f"  Got only {len(utterances)}/{n_utterances} for {intent_name}"
            )

        # Cache the result
        if cache is not None:
            cache[cache_key] = utterances

        logger.info(f"  Generated {len(utterances)} utterances for {intent_name}")
        return utterances

    except Exception as e:
        logger.error(f"  Groq API call failed for {intent_name}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate real utterance test set using Groq API'
    )
    parser.add_argument(
        '--per-class', type=int, default=40,
        help='Number of utterances to generate per class (default: 40)',
    )
    parser.add_argument(
        '--no-cache', action='store_true',
        help='Ignore cached results and regenerate all',
    )
    parser.add_argument(
        '--use-rag', action='store_true',
        help=(
            'Fetch real textbook passages from the RAG pipeline and inject them '
            'into the On-Topic generation prompt. Requires rag_pipeline to be '
            'configured and ChromaDB to be indexed.'
        ),
    )
    args = parser.parse_args()

    # ── Groq client setup ──────────────────────────────────────────
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv('GROQ_API_KEY', '')
    if not api_key:
        logger.error(
            "GROQ_API_KEY not set. Add it to your .env file or set it as an "
            "environment variable."
        )
        return

    from groq import Groq
    client = Groq(api_key=api_key)

    cache = {} if args.no_cache else _load_cache()

    # ── RAG passage prefetch ──────────────────────────────────────
    rag_passages: list[str] = []
    if args.use_rag:
        print('[RAG] Pre-fetching passages for all Python topics...')
        for topic in PYTHON_TOPICS:
            rag_passages.extend(_fetch_rag_passages_for_topic(topic, top_k=3))
            time.sleep(0.2)
        print(f'[RAG] {len(rag_passages)} total passages fetched.\n')

    print(f"\n{'='*60}")
    print(f"Generating Real Utterance Test Set via Groq ({MODEL})")
    print(f"{'='*60}")
    print(f"Target: {args.per_class} utterances × {len(LABEL_MAP)} classes = "
          f"{args.per_class * len(LABEL_MAP)} total\n")

    all_rows = []
    for intent_name, label_id in LABEL_MAP.items():
        print(f"[{label_id + 1}/{len(LABEL_MAP)}] Generating: {intent_name}")

        utterances = generate_utterances_for_class(
            client, intent_name, n_utterances=args.per_class, cache=cache,
            rag_passages=rag_passages if (args.use_rag and intent_name == 'On-Topic Question') else None,
        )

        # Rate limit: Groq has a tokens-per-minute cap
        time.sleep(2)

        for utt in utterances:
            all_rows.append({
                'student_input': utt.strip(),
                'session_context': generate_random_context(),
                'label': label_id,
                'intent_name': intent_name,
            })

    _save_cache(cache)

    # ── Write output ───────────────────────────────────────────────
    df = pd.DataFrame(all_rows)
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    print(f"\n{'='*60}")
    print(f"[+] Generated {len(df)} utterances → {OUTPUT_PATH}")
    print(f"{'='*60}")
    print(f"\nDistribution:")
    print(df['intent_name'].value_counts().to_string())
    print(f"\nSample utterances:")
    for name in LABEL_MAP:
        subset = df[df['intent_name'] == name]
        if len(subset) > 0:
            sample = subset.iloc[0]['student_input']
            print(f"  {name}: \"{sample}\"")


if __name__ == '__main__':
    main()
