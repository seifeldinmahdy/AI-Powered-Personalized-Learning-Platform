"""
Dataset Generation Pipeline for TinyBert-CNN Intent Classifier.
Generates (student_input, session_context, label) triples for 5-class classification.
"""

import random
import pandas as pd
import os
import re

# ─────────────────────────────────────────────────────────────────────
# CONSTANTS & METADATA
# ─────────────────────────────────────────────────────────────────────

PYTHON_TOPICS = [
    "Variables and Data Types",
    "Strings and Formatting",
    "Arithmetic Operators",
    "Boolean Logic",
    "If/Else Conditionals",
    "For Loops",
    "While Loops",
    "Lists and Tuples",
    "Dictionaries",
    "Sets",
    "Functions and Scope",
    "Lambda Functions",
    "Error Handling (Try/Except)",
    "Classes and OOP",
    "File Handling"
]

LABEL_MAP = {
    'On-Topic Question': 0,
    'Off-Topic Question': 1,
    'Emotional-State': 2,
    'Pace-Related': 3,
    'Repeat/clarification': 4
}

EMOTIONS = ["neutral", "engaged", "focused", "frustrated", "confused", "bored", "tired", "anxious", "excited", "overwhelmed"]
PACES = ["normal", "fast", "slow", "rushed", "dragging", "moderate", "steady"]

# ─────────────────────────────────────────────────────────────────────
# CONTEXT GENERATION (Compact key-value format)
# ─────────────────────────────────────────────────────────────────────

def generate_session_context(current_topic_idx):
    """Generates a compact session context string."""
    current_topic = PYTHON_TOPICS[current_topic_idx]

    if current_topic_idx > 0:
        prev_count = min(3, current_topic_idx)
        prev_topics = PYTHON_TOPICS[current_topic_idx - prev_count : current_topic_idx]
    else:
        prev_topics = []

    # Ability scores for previous topics
    abilities = []
    for pt in prev_topics:
        short_name = pt.split("(")[0].strip().replace(" and ", "&")
        score = random.randint(30, 100)
        abilities.append(f"{short_name}:{score}%")

    ability_str = ",".join(abilities) if abilities else "N/A"
    prev_str = ",".join([t.split("(")[0].strip() for t in prev_topics]) if prev_topics else "None"
    emotion = random.choice(EMOTIONS)
    pace = random.choice(PACES)
    slide = random.randint(5, 60)

    context = (
        f"topic:{current_topic} | "
        f"prev:{prev_str} | "
        f"ability:{ability_str} | "
        f"emotion:{emotion} | "
        f"pace:{pace} | "
        f"slides:{slide-1},{slide},{slide+1}"
    )
    return context, current_topic, prev_topics


# ─────────────────────────────────────────────────────────────────────
# EXPANDED TEMPLATE BANKS (40+ per class)
# ─────────────────────────────────────────────────────────────────────

ON_TOPIC_TEMPLATES = [
    # Direct questions
    "How do I use {topic} in my code?",
    "Can you explain {topic} again?",
    "What are the best practices for {topic}?",
    "Can you show me an example of {topic}?",
    "Why is {topic} giving me a syntax error?",
    "Is there a different way to write {topic}?",
    "I don't get the part about {topic}.",
    "Can we do another exercise for {topic}?",
    "What happens if I forget to close the bracket in {topic}?",
    "How is {topic} different from the previous topic?",
    # Conceptual questions
    "Why do we need {topic}?",
    "When should I use {topic} vs the other approach?",
    "What's the point of {topic}?",
    "Is {topic} used a lot in real projects?",
    "Can you give me a real-world example of {topic}?",
    "Does {topic} work the same way in other languages?",
    # Problem-solving
    "I'm stuck on this challenge about {topic}.",
    "My code for {topic} isn't working, can you help?",
    "I keep getting an error with {topic}.",
    "Why does my {topic} code print the wrong output?",
    "What am I doing wrong with {topic}?",
    "Can you debug this {topic} example with me?",
    # Clarification on current material
    "What did you mean when you said {topic} works like that?",
    "Can you go deeper into {topic}?",
    "Is there more to know about {topic}?",
    "How does {topic} connect to what we learned before?",
    "What's the difference between the two approaches you showed for {topic}?",
    "Can you break down {topic} step by step?",
    # Practical application
    "How would I use {topic} in a project?",
    "Can I combine {topic} with what we learned earlier?",
    "Is {topic} something I'll use every day?",
    "Where does {topic} fit in a larger program?",
    "Can you show me a more advanced use of {topic}?",
    # Short/informal
    "Tell me more about {topic}",
    "What's {topic} again?",
    "{topic} is confusing",
    "Help me with {topic}",
    "I need help understanding {topic}",
    "So how does {topic} actually work?",
    "Wait, explain {topic} one more time",
]

# Context-aware on-topic templates (reference ability scores, prev topics)
ON_TOPIC_CONTEXT_TEMPLATES = [
    "You said I scored low on {prev_topic}, does that affect how I should approach {topic}?",
    "Since I did well on {prev_topic}, is {topic} going to be similar?",
    "How does {prev_topic} relate to {topic}?",
    "I understood {prev_topic} but {topic} feels completely different, why?",
    "Can we review {prev_topic} briefly before diving deeper into {topic}?",
    "My score on {prev_topic} was not great, will I need it for {topic}?",
]

OFF_TOPIC_GENERAL = [
    "What's the weather like today?",
    "How do I cook pasta?",
    "Who won the soccer match last night?",
    "Can you recommend a good movie to watch?",
    "What is the capital of France?",
    "How much does a new car cost?",
    "Do you like listening to music?",
    "Tell me a joke.",
    "I'm feeling hungry, should I order pizza?",
    "What is your favorite color?",
    "What time is it?",
    "Do you know any good restaurants nearby?",
    "Who is the president of the United States?",
    "What's the best phone to buy right now?",
    "Can you help me with my math homework?",
    "How tall is the Eiffel Tower?",
    "What should I eat for dinner?",
    "Do you watch Netflix?",
    "What's the meaning of life?",
    "How do I fix my car?",
]

OFF_TOPIC_FUTURE_TOPIC_TEMPLATES = [
    "Are we going to learn about {topic} soon?",
    "What is {topic} exactly?",
    "I heard about {topic}, can you explain it to me?",
    "How does {topic} work in Python?",
    "Can we skip ahead to {topic}?",
    "Is {topic} hard to learn?",
    "I saw someone using {topic}, what does it do?",
    "Do we need to know about {topic}?",
    "When will we cover {topic}?",
    "My friend told me {topic} is important, is that true?",
    "Will {topic} be on the exam?",
    "Can you give me a sneak peek of {topic}?",
    "I already know a bit about {topic}, can we jump to it?",
    "How long until we get to {topic}?",
    "Is {topic} related to what we are doing now?",
]

EMOTIONAL_TEMPLATES = [
    # Frustration
    "I am so frustrated right now.",
    "This is making me really angry.",
    "I can't take this anymore.",
    "I feel like giving up.",
    "Nothing makes sense to me.",
    "I'm losing my patience.",
    "Why is this so hard?",
    "I feel stupid for not getting this.",
    # Positive
    "This is really starting to make sense!",
    "I love coding, this is fun!",
    "Wow, I finally understand it!",
    "I am ready to tackle the next challenge!",
    "This is getting exciting!",
    "I feel so good about this now.",
    "I'm having a great time learning this.",
    "That was actually easier than I thought.",
    # Confusion
    "I feel completely stuck and confused.",
    "I have no idea what's going on.",
    "My brain is fried.",
    "I'm lost.",
    "I don't understand anything.",
    "This is so confusing it hurts.",
    # Boredom / tiredness
    "This is getting boring.",
    "I'm feeling super tired today.",
    "My head hurts from all this information.",
    "I feel like I'm not making any progress.",
    "Can we do something more interesting?",
    "I'm so sleepy right now.",
    "This is not engaging at all.",
    "My eyes are glazing over.",
    # Anxiety
    "I'm nervous about the upcoming test.",
    "What if I fail?",
    "I feel anxious about falling behind.",
    "Everyone else seems to get it except me.",
    "I'm stressed out.",
    # Mixed / ambiguous (touches emotional + other intents)
    "I'm confused, I feel so dumb right now.",
    "I'm excited but also scared I'll mess up.",
    "I'm frustrated because this used to make sense.",
    "I feel overwhelmed by all this new stuff.",
    "I just feel really down today.",
]

PACE_TEMPLATES = [
    # Slow down
    "Can we slow down a bit?",
    "You are going way too fast.",
    "Wait, can you slow down the explanation?",
    "I need more time to process this.",
    "Can you wait a second before moving to the next slide?",
    "Hold on, I'm still writing notes.",
    "Please slow down, I can't keep up.",
    "You're moving too quickly for me.",
    "I need a moment to think about this.",
    "Can we pause for a minute?",
    "Don't rush through this please.",
    "Slow down, I'm still on the last example.",
    "Give me a sec, I'm still processing.",
    # Speed up
    "Let's move on to the next topic.",
    "Can we skip this?",
    "I think I got this, let's speed up.",
    "Can we go through the next part faster?",
    "Let's speed up the pace, I'm bored.",
    "I already know this, can we move on?",
    "This part is easy, let's go faster.",
    "Skip ahead please.",
    "Next topic please.",
    "We're spending too long on this.",
    "Can we pick up the pace?",
    # Break / timing
    "Can we take a break?",
    "How much time do we have left?",
    "When does this session end?",
    "I need a 5 minute break.",
    "Let's take a quick breather.",
    # General pacing
    "The pace feels about right.",
    "Can you adjust the speed a bit?",
    "I think the pacing is off.",
    "Are we on schedule?",
    "How many more slides do we have?",
]

REPEAT_TEMPLATES = [
    "Can you repeat that last part?",
    "What did you say about the slide right before this one?",
    "Could you clarify what you meant?",
    "I didn't catch that, can you say it again?",
    "Say that again?",
    "Can you go back to the previous slide for a second?",
    "I missed the first step, can you re-explain?",
    "Can you repeat the rule for that?",
    "Could you run through the explanation one more time?",
    "Can you clarify the difference between the two examples?",
    "Wait, what was that?",
    "Huh? Can you repeat?",
    "I didn't understand, please say it again.",
    "Sorry, I zoned out. What did you just say?",
    "Come again?",
    "Can you show that example one more time?",
    "Go back to that last point please.",
    "I need you to repeat the definition.",
    "What was the syntax you just showed?",
    "Can you re-explain how that works?",
    "I lost you there, can you start over on that point?",
    "Please repeat the steps.",
    "Sorry, can you go over that again from the beginning?",
    "What was the output of that code again?",
    "Can you re-run that example?",
    "I missed it, one more time please.",
    "I need to hear that explanation again.",
    "Can you walk me through that once more?",
    "Let me see that slide again.",
    "I need a recap of what you just said.",
    "Can you summarize what you just explained?",
    "What were the key points of that last section?",
]


# ─────────────────────────────────────────────────────────────────────
# AUGMENTATION STRATEGIES
# ─────────────────────────────────────────────────────────────────────

SYNONYM_MAP = {
    "explain": ["describe", "clarify", "elaborate on", "break down", "walk me through"],
    "show": ["demonstrate", "present", "display", "give me"],
    "help": ["assist", "support", "aid"],
    "use": ["utilize", "apply", "work with"],
    "understand": ["get", "grasp", "comprehend", "follow"],
    "repeat": ["say again", "go over again", "redo", "recap"],
    "confused": ["lost", "puzzled", "unsure", "baffled"],
    "stuck": ["blocked", "stalled", "unable to proceed"],
    "slow down": ["take it easy", "go slower", "ease up"],
    "speed up": ["go faster", "pick up the pace", "hurry up"],
    "example": ["demo", "sample", "illustration", "instance"],
    "error": ["bug", "mistake", "issue", "problem"],
    "different": ["alternative", "another", "other"],
    "code": ["program", "script", "snippet"],
}

FILLERS = ["umm", "so", "like", "hey", "well", "basically", "honestly", "actually", "ok so", "right"]

def augment_synonym(text):
    """Replace one random word with a synonym."""
    for word, synonyms in SYNONYM_MAP.items():
        if word in text.lower() and random.random() < 0.35:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            text = pattern.sub(random.choice(synonyms), text, count=1)
            break
    return text

def augment_case(text):
    """Randomly change casing."""
    r = random.random()
    if r < 0.3:
        return text.lower()
    if r < 0.38:
        return text.upper()
    return text

def augment_punctuation(text):
    """Randomly alter punctuation."""
    r = random.random()
    if r < 0.25:
        return text.rstrip("?!.") + "?"
    if r < 0.4:
        return text.rstrip("?!.")
    if r < 0.48:
        return text.rstrip("?!.") + "!!"
    return text

def augment_filler(text):
    """Randomly prepend a filler word."""
    if random.random() < 0.2:
        return random.choice(FILLERS) + " " + text
    return text

def augment_typo(text, prob=0.08):
    """Inject character-level typos."""
    if random.random() > 0.35:
        return text
    chars = list(text)
    for i in range(len(chars)):
        if random.random() < prob and chars[i].isalpha():
            op = random.choice(["swap", "delete", "duplicate"])
            if op == "swap" and i < len(chars) - 1:
                chars[i], chars[i+1] = chars[i+1], chars[i]
            elif op == "delete":
                chars[i] = ""
            elif op == "duplicate":
                chars[i] = chars[i] * 2
    return "".join(chars)

def augment_word_swap(text):
    """Swap two adjacent words."""
    words = text.split()
    if len(words) <= 2 or random.random() > 0.15:
        return text
    idx = random.randint(0, len(words) - 2)
    words[idx], words[idx+1] = words[idx+1], words[idx]
    return " ".join(words)

def augment_word_delete(text):
    """Delete a random non-essential word."""
    words = text.split()
    if len(words) <= 3 or random.random() > 0.12:
        return text
    idx = random.randint(1, len(words) - 2)
    words.pop(idx)
    return " ".join(words)

def augment_text(text):
    """Apply a random combination of augmentation strategies."""
    strategies = [augment_synonym, augment_case, augment_punctuation,
                  augment_filler, augment_typo, augment_word_swap, augment_word_delete]
    # Apply 1-3 random strategies
    chosen = random.sample(strategies, k=random.randint(1, 3))
    for fn in chosen:
        text = fn(text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────
# INTENT GENERATORS
# ─────────────────────────────────────────────────────────────────────

def get_on_topic_question(current_topic, prev_topics):
    # 20% chance of context-aware template if prev_topics exist
    if prev_topics and random.random() < 0.2:
        prev_topic = random.choice(prev_topics)
        template = random.choice(ON_TOPIC_CONTEXT_TEMPLATES)
        return template.replace("{topic}", current_topic).replace("{prev_topic}", prev_topic)
    template = random.choice(ON_TOPIC_TEMPLATES)
    return template.replace("{topic}", current_topic)

def get_off_topic_question(current_topic_idx):
    if current_topic_idx < len(PYTHON_TOPICS) - 1 and random.random() < 0.5:
        future_topic = random.choice(PYTHON_TOPICS[current_topic_idx + 1:])
        template = random.choice(OFF_TOPIC_FUTURE_TOPIC_TEMPLATES)
        return template.replace("{topic}", future_topic)
    return random.choice(OFF_TOPIC_GENERAL)

def get_emotional_state():
    return random.choice(EMOTIONAL_TEMPLATES)

def get_pace_related():
    return random.choice(PACE_TEMPLATES)

def get_repeat_clarification():
    return random.choice(REPEAT_TEMPLATES)


# ─────────────────────────────────────────────────────────────────────
# PIPELINE GENERATION (3-way split: train/val/test)
# ─────────────────────────────────────────────────────────────────────

def build_dataset(num_samples_per_class=2000, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15):
    print(f"Starting Dataset Generation ({num_samples_per_class} per class)...")

    dataset = []

    for intent, label_id in LABEL_MAP.items():
        for _ in range(num_samples_per_class):
            topic_idx = random.randint(0, len(PYTHON_TOPICS) - 1)
            context_str, current_topic, prev_topics = generate_session_context(topic_idx)

            if intent == 'On-Topic Question':
                student_input = get_on_topic_question(current_topic, prev_topics)
            elif intent == 'Off-Topic Question':
                student_input = get_off_topic_question(topic_idx)
            elif intent == 'Emotional-State':
                student_input = get_emotional_state()
            elif intent == 'Pace-Related':
                student_input = get_pace_related()
            elif intent == 'Repeat/clarification':
                student_input = get_repeat_clarification()
            else:
                student_input = get_off_topic_question(topic_idx)

            student_input = augment_text(student_input)

            dataset.append({
                'student_input': student_input,
                'session_context': context_str,
                'label': label_id,
                'intent_name': intent
            })

    df = pd.DataFrame(dataset)
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    # Stratified 3-way split
    train_dfs, val_dfs, test_dfs = [], [], []
    for label_id in sorted(df['label'].unique()):
        label_df = df[df['label'] == label_id].reset_index(drop=True)
        n = len(label_df)
        t1 = int(n * train_ratio)
        t2 = int(n * (train_ratio + val_ratio))
        train_dfs.append(label_df.iloc[:t1])
        val_dfs.append(label_df.iloc[t1:t2])
        test_dfs.append(label_df.iloc[t2:])

    train_df = pd.concat(train_dfs).sample(frac=1, random_state=42).reset_index(drop=True)
    val_df = pd.concat(val_dfs).sample(frac=1, random_state=42).reset_index(drop=True)
    test_df = pd.concat(test_dfs).sample(frac=1, random_state=42).reset_index(drop=True)

    output_dir = 'data'
    os.makedirs(output_dir, exist_ok=True)

    train_df.to_csv(os.path.join(output_dir, 'train.csv'), index=False)
    val_df.to_csv(os.path.join(output_dir, 'val.csv'), index=False)
    test_df.to_csv(os.path.join(output_dir, 'test.csv'), index=False)

    print("[+] Data Generation Complete!")
    print(f"Total: {len(df)} | Train: {len(train_df)} | Val: {len(val_df)} | Test: {len(test_df)}")
    print(f"Train distribution:\n{train_df['label'].value_counts().sort_index().to_string()}")


if __name__ == '__main__':
    build_dataset(num_samples_per_class=2000)
