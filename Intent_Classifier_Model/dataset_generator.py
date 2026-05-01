"""
Dataset Generation Pipeline for TinyBert-CNN Intent Classifier.
Generates (student_input, session_context, label) triples for 5-class classification.

New features:
- LLM-based paraphrase augmentation (--augment-llm flag)
- Fixed template-label mismatches
- Colloquial / ultra-short emotional samples
"""

import argparse
import json
import random
import pandas as pd
import os
import re
import logging

logger = logging.getLogger(__name__)

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
    # MOVED to REPEAT: "Can you explain {topic} again?"
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
    "So how does {topic} actually work?"
]

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
    # REMOVED: "I can't take this anymore." (Ambiguous with Pace/Break requests)
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
    # REMOVED: "This is getting boring." (Ambiguous with Pace/Speed up requests)
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
    # Colloquial / profanity / ultra-short expressions
    "wtf",
    "bruh",
    "i give up",
    "this is bs",
    "lmaooo im lost",
    "fml",
    "im done",
    "ugh",
    "smh",
    "nah bro",
    "this sucks",
    "kill me",
    "yo what",
    "no way",
    "i cant even",
    "bro what",
    "im so done rn",
    "bruhhh",
    "pain",
    "crying rn",
    "this aint it",
    "dawg im cooked",
    "i hate this",
    "yooo lets go",
    "lessgoo i got it",
    "ayy thats sick",
    "ngl this is hard",
    "lowkey confused",
    "highkey stressed",
    "im tweaking",
    "bruh moment",
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
    # REMOVED: "Let's speed up the pace, I'm bored." (Ambiguous with Emotional/Boredom)
    "I already know this, can we move on?",
    "This part is easy, let's go faster.",
    "Skip ahead please.",
    "Next topic please.",
    "We're spending too long on this.",
    "Can we pick up the pace?",
    # Break / timing
    # REMOVED: "Can we take a break?" (Ambiguous: is it Pace or Emotional exhaustion?)
    "How much time do we have left?",
    "When does this session end?",
    # REMOVED: "I need a 5 minute break." (Ambiguous)
    # REMOVED: "Let's take a quick breather." (Ambiguous)
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
    "Can you explain {topic} again?",
    "Wait, explain {topic} one more time",
]

# ─────────────────────────────────────────────────────────────────────
# REAL-WORLD EXAMPLES & HELD-OUT TEMPLATES
# ─────────────────────────────────────────────────────────────────────

PACE_REAL = [
    "slow", "SLOW DOWN", "wait wait wait", "too fast bro",
    "pause", "hold on", "omg slow", "faster", "speed up pls",
    "one sec", "wait up", "can we stop for a sec", "slow tf down",
    "hol up", "chill for a sec", "can you slow down", "ur going too fast",
    "speed it up", "go faster", "i already know this go faster",
    "too slow", "skip this", "can we skip", # REMOVED "im bored speed up"
    "next slide", "next", "hurry up", "wait go back", "slow down im typing",
    "pause pls", "give me a sec", "wait a minute", "hang on",
    "stop going so fast", "i need a minute", "can we pause",
    "move on", "lets keep going", "skip to the next part", "faster please"
]

REPEAT_REAL = [
    "huh?", "what?", "again?", "come again", "??",
    "sorry what", "didn't get that", "repeat", "say again",
    "what did you just say", "lost u there", "i missed that",
    "say that one more time", "can u repeat", "what was that",
    "i wasn't listening", "go over that again", "what did u say",
    "rewind", "say it again", "what u mean", "huh",
    "pardon?", "could u repeat", "i didnt catch that",
    "can we go over that again", "run that back", "one more time",
    "what?", "say what", "i'm confused repeat please",
    "what happened?", "can you say that again", "i missed the last part",
    "wait what?", "what was the last thing u said", "repeat pls",
    "explain that again", "did not hear you", "what did i miss"
]

OFF_TOPIC_REAL = [
    "what's 2+2", "who made you", "are you chatgpt",
    "what time is it", "tell me a joke", "what's the weather",
    "help me with my homework", "what should i eat",
    "do you have feelings", "who won yesterday",
    "whats your favorite color", "do u play games", "whats good",
    "how are you", "are you a robot", "can u do my math",
    "whats the meaning of life", "who is the president", "im hungry",
    "where are u from", "whats ur name", "can we talk about something else",
    "sing me a song", "do u like pizza", "tell me a story",
    "who won the superbowl", "what day is it", "whats up",
    "how old are you", "what's your iq", "do you sleep",
    "can you write an essay for me", "give me the answers", "hello",
    "hi", "yo", "sup", "howdy", "good morning", "whats the capital of france"
]

ON_TOPIC_REAL = [
    "i dont get it", "what does this do", "why does it break",
    "show me", "example pls", "what's the difference",
    "how does that work", "im confused about this part",
    "can you show me with code", "what does {topic} even mean",
    "how do i use {topic}", "give me an example of {topic}",
    "why use {topic}", "im stuck on {topic}", "my {topic} code is broken",
    "what am i doing wrong", "how is this useful", "can u show another example",
    "is this important", "do we need to know this", "whats the syntax",
    "how do i write this", "i keep getting an error", "why am i getting an error",
    "what does that mean", "explain the code", "what does this line do",
    "i don't understand the example", "can u break this down", "more examples pls",
    "im not getting {topic}", "help me fix this", "is there another way to do this",
    "can you explain this simply", "how does {topic} work", "why do we do this",
    "whats a good use case for {topic}", "when would i use this", "what is {topic}"
]

EMOTIONAL_REAL = [
    "i hate this so much", "this is impossible", "im crying",
    "my brain hurts", "i feel so dumb", "this is too hard",
    "i quit", "make it stop", "i am so mad right now",
    "yay i did it", "this is fun", "i love coding",
    "omg it works", "i feel smart", "let's goooo",
    "im so tired", "im exhausted", # REMOVED "can we stop" (Ambiguous with Pace)
    "my eyes hurt", "i need to sleep" # REMOVED "this is boring" (Ambiguous with Pace check)
]

HELD_OUT_PACE = ["wait up", "STOP", "too fast omg", "one moment"]
HELD_OUT_REPEAT = ["huh?", "what??", "come again?", "i missed that"]
HELD_OUT_EMOTION = ["wtf", "i give up", "bruh", "this is pointless"]
HELD_OUT_ON_TOPIC = ["show me an example", "why does it break", "i don't get it"]
HELD_OUT_OFF_TOPIC = ["are you an AI", "what time is it", "tell me a joke"]

# REMOVED extend() calls that injected *_REAL directly into main lists.
# They will be injected later specifically into the _TRAIN partitions.

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
# INTENT TEMPLATE PARTITIONING (TRAIN/VAL/TEST)
# ─────────────────────────────────────────────────────────────────────

def partition_bank(bank: list, seed: int = 42) -> tuple:
    """Strictly partition a template bank into non-overlapping thirds: Train, Val, Test."""
    # Deterministic split
    rng = random.Random(seed)
    shuffled = bank.copy()
    rng.shuffle(shuffled)
    n = len(shuffled)
    return shuffled[:n//3], shuffled[n//3:2*n//3], shuffled[2*n//3:]

# Split main template banks into non-overlapping thirds
ON_TOPIC_TRAIN, ON_TOPIC_VAL, ON_TOPIC_TEST = partition_bank(ON_TOPIC_TEMPLATES)
ON_TOPIC_CTX_TRAIN, ON_TOPIC_CTX_VAL, ON_TOPIC_CTX_TEST = partition_bank(ON_TOPIC_CONTEXT_TEMPLATES)
OFF_TOPIC_GEN_TRAIN, OFF_TOPIC_GEN_VAL, OFF_TOPIC_GEN_TEST = partition_bank(OFF_TOPIC_GENERAL)
OFF_TOPIC_FUT_TRAIN, OFF_TOPIC_FUT_VAL, OFF_TOPIC_FUT_TEST = partition_bank(OFF_TOPIC_FUTURE_TOPIC_TEMPLATES)
EMOTIONAL_TRAIN, EMOTIONAL_VAL, EMOTIONAL_TEST = partition_bank(EMOTIONAL_TEMPLATES)
PACE_TRAIN, PACE_VAL, PACE_TEST = partition_bank(PACE_TEMPLATES)
REPEAT_TRAIN, REPEAT_VAL, REPEAT_TEST = partition_bank(REPEAT_TEMPLATES)

# Inject *_REAL lists ONLY into the training splits to avoid cross-contamination
_held_out_all = set(HELD_OUT_PACE + HELD_OUT_REPEAT + HELD_OUT_EMOTION +
                    HELD_OUT_ON_TOPIC + HELD_OUT_OFF_TOPIC)

PACE_TRAIN.extend([x for x in PACE_REAL if x not in _held_out_all])
REPEAT_TRAIN.extend([x for x in REPEAT_REAL if x not in _held_out_all])
EMOTIONAL_TRAIN.extend([x for x in EMOTIONAL_REAL if x not in _held_out_all])
ON_TOPIC_TRAIN.extend([x for x in ON_TOPIC_REAL if x not in _held_out_all])
OFF_TOPIC_GEN_TRAIN.extend([x for x in OFF_TOPIC_REAL if x not in _held_out_all])

# ─────────────────────────────────────────────────────────────────────
# INTENT GENERATORS
# ─────────────────────────────────────────────────────────────────────

def get_on_topic_question(current_topic, prev_topics, split_name='train'):
    if split_name == 'test' and random.random() < 0.5:
        template = random.choice(HELD_OUT_ON_TOPIC)
        return template.replace("{topic}", current_topic)

    # Dispatch to appropriate split bank
    if split_name == 'val':
        bank = ON_TOPIC_VAL
        ctx_bank = ON_TOPIC_CTX_VAL
    elif split_name == 'test':
        bank = ON_TOPIC_TEST
        ctx_bank = ON_TOPIC_CTX_TEST
    else: # train
        bank = ON_TOPIC_TRAIN
        ctx_bank = ON_TOPIC_CTX_TRAIN

    if prev_topics and random.random() < 0.2 and len(ctx_bank) > 0:
        prev_topic = random.choice(prev_topics)
        template = random.choice(ctx_bank)
        return template.replace("{topic}", current_topic).replace("{prev_topic}", prev_topic)
    template = random.choice(bank)
    return template.replace("{topic}", current_topic)

def get_off_topic_question(current_topic_idx, split_name='train'):
    if split_name == 'test' and random.random() < 0.5:
        return random.choice(HELD_OUT_OFF_TOPIC)

    if split_name == 'val':
        fut_bank = OFF_TOPIC_FUT_VAL
        gen_bank = OFF_TOPIC_GEN_VAL
    elif split_name == 'test':
        fut_bank = OFF_TOPIC_FUT_TEST
        gen_bank = OFF_TOPIC_GEN_TEST
    else:
        fut_bank = OFF_TOPIC_FUT_TRAIN
        gen_bank = OFF_TOPIC_GEN_TRAIN

    if current_topic_idx < len(PYTHON_TOPICS) - 1 and random.random() < 0.5 and len(fut_bank) > 0:
        future_topic = random.choice(PYTHON_TOPICS[current_topic_idx + 1:])
        template = random.choice(fut_bank)
        return template.replace("{topic}", future_topic)
    return random.choice(gen_bank)

def get_emotional_state(split_name='train'):
    if split_name == 'test' and random.random() < 0.5:
        return random.choice(HELD_OUT_EMOTION)
    
    if split_name == 'val':
        return random.choice(EMOTIONAL_VAL)
    elif split_name == 'test':
        return random.choice(EMOTIONAL_TEST)
    return random.choice(EMOTIONAL_TRAIN)

def get_pace_related(split_name='train'):
    if split_name == 'test' and random.random() < 0.5:
        return random.choice(HELD_OUT_PACE)
    
    if split_name == 'val':
        return random.choice(PACE_VAL)
    elif split_name == 'test':
        return random.choice(PACE_TEST)
    return random.choice(PACE_TRAIN)

def get_repeat_clarification(split_name='train'):
    if split_name == 'test' and random.random() < 0.5:
        return random.choice(HELD_OUT_REPEAT)
    
    if split_name == 'val':
        return random.choice(REPEAT_VAL)
    elif split_name == 'test':
        return random.choice(REPEAT_TEST)
    return random.choice(REPEAT_TRAIN)

# ─────────────────────────────────────────────────────────────────────
# PIPELINE GENERATION (3-way split: train/val/test)
# ─────────────────────────────────────────────────────────────────────

def build_dataset(num_samples_per_class=2000, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15):
    print(f"Starting Dataset Generation ({num_samples_per_class} per class)...")

    train_samples = int(num_samples_per_class * train_ratio)
    val_samples = int(num_samples_per_class * val_ratio)
    test_samples = num_samples_per_class - train_samples - val_samples

    def generate_split(samples_per_class, split_name, is_test):
        dataset = []
        apply_augmentation = split_name == 'train'
        for intent, label_id in LABEL_MAP.items():
            for _ in range(samples_per_class):
                topic_idx = random.randint(0, len(PYTHON_TOPICS) - 1)
                context_str, current_topic, prev_topics = generate_session_context(topic_idx)

                if intent == 'On-Topic Question':
                    student_input = get_on_topic_question(current_topic, prev_topics, split_name=split_name)
                elif intent == 'Off-Topic Question':
                    student_input = get_off_topic_question(topic_idx, split_name=split_name)
                elif intent == 'Emotional-State':
                    student_input = get_emotional_state(split_name=split_name)
                elif intent == 'Pace-Related':
                    student_input = get_pace_related(split_name=split_name)
                elif intent == 'Repeat/clarification':
                    student_input = get_repeat_clarification(split_name=split_name)
                else:
                    student_input = get_off_topic_question(topic_idx, split_name=split_name)

                if apply_augmentation:
                    student_input = augment_text(student_input)

                dataset.append({
                    'student_input': student_input,
                    'session_context': context_str,
                    'label': label_id,
                    'intent_name': intent
                })
        df = pd.DataFrame(dataset)
        return df.sample(frac=1, random_state=42).reset_index(drop=True)

    train_df = generate_split(train_samples, split_name='train', is_test=False)
    val_df = generate_split(val_samples, split_name='val', is_test=False)
    test_df = generate_split(test_samples, split_name='test', is_test=True)

    output_dir = 'data'
    os.makedirs(output_dir, exist_ok=True)

    train_df.to_csv(os.path.join(output_dir, 'train.csv'), index=False)
    val_df.to_csv(os.path.join(output_dir, 'val.csv'), index=False)
    test_df.to_csv(os.path.join(output_dir, 'test.csv'), index=False)

    df = pd.concat([train_df, val_df, test_df])
    print("[+] Data Generation Complete!")
    print(f"Total: {len(df)} | Train: {len(train_df)} | Val: {len(val_df)} | Test: {len(test_df)}")
    print(f"Train distribution:\n{train_df['label'].value_counts().sort_index().to_string()}")

    return train_df, val_df, test_df


# ─────────────────────────────────────────────────────────────────────
# LLM-BASED PARAPHRASE AUGMENTATION
# ─────────────────────────────────────────────────────────────────────

PARAPHRASE_CACHE_PATH = os.path.join('data', 'paraphrase_cache.json')

def _load_paraphrase_cache() -> dict:
    """Load cached paraphrases from disk."""
    if os.path.exists(PARAPHRASE_CACHE_PATH):
        with open(PARAPHRASE_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def _save_paraphrase_cache(cache: dict) -> None:
    """Save paraphrase cache to disk."""
    os.makedirs(os.path.dirname(PARAPHRASE_CACHE_PATH), exist_ok=True)
    with open(PARAPHRASE_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def paraphrase_with_llm(
    samples: list[str],
    label_name: str,
    n_paraphrases: int = 3,
    batch_size: int = 10,
) -> list[str]:
    """Generate paraphrases for training samples using the Groq API."""
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv('GROQ_API_KEY', '')
    if not api_key:
        logger.warning('GROQ_API_KEY not set — skipping LLM paraphrase augmentation')
        return []

    from groq import Groq
    client = Groq(api_key=api_key)

    cache = _load_paraphrase_cache()
    all_paraphrases: list[str] = []

    for i in range(0, len(samples), batch_size):
        batch = samples[i:i + batch_size]
        uncached = [s for s in batch if s not in cache]

        if uncached:
            numbered = '\n'.join(f'{j+1}. {s}' for j, s in enumerate(uncached))
            prompt = (
                f'You are a data augmentation assistant. For each student utterance below '
                f'(intent class: "{label_name}"), generate exactly {n_paraphrases} realistic '
                f'paraphrases that a real student might say. Vary formality, slang, and length. '
                f'Return ONLY a JSON object: {{"paraphrases": [[p1,p2,p3], ...]}}\n\n{numbered}'
            )
            try:
                resp = client.chat.completions.create(
                    model='llama-3.1-8b-instant',
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.8,
                    max_tokens=2048,
                    response_format={'type': 'json_object'},
                )
                text = resp.choices[0].message.content.strip()
                data = json.loads(text)
                groups = data.get('paraphrases', [])
                for s, group in zip(uncached, groups):
                    cache[s] = group if isinstance(group, list) else []
            except Exception as e:
                logger.error('LLM paraphrase batch failed: %s', e)
                for s in uncached:
                    cache[s] = []

        for s in batch:
            all_paraphrases.extend(cache.get(s, []))

    _save_paraphrase_cache(cache)
    print(f'[+] LLM paraphrase augmentation: {len(all_paraphrases)} new samples for "{label_name}"')
    return all_paraphrases

def augment_dataset_with_llm(df: pd.DataFrame, n_paraphrases: int = 3) -> pd.DataFrame:
    """Augment every class in the dataset with LLM-generated paraphrases."""
    intent_names = {v: k for k, v in LABEL_MAP.items()}
    new_rows = []

    for label_id in sorted(df['label'].unique()):
        label_name = intent_names.get(label_id, f'label_{label_id}')
        subset = df[df['label'] == label_id]
        texts = subset['student_input'].tolist()
        contexts = subset['session_context'].tolist()

        paraphrases = paraphrase_with_llm(texts, label_name, n_paraphrases)

        for j, para in enumerate(paraphrases):
            ctx = contexts[j % len(contexts)] if contexts else ''
            new_rows.append({
                'student_input': para,
                'session_context': ctx,
                'label': label_id,
                'intent_name': label_name,
            })

    aug_df = pd.DataFrame(new_rows)
    combined = pd.concat([df, aug_df], ignore_index=True)
    combined = combined.sample(frac=1, random_state=42).reset_index(drop=True)
    print(f'[+] Dataset augmented: {len(df)} -> {len(combined)} rows')
    return combined

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate intent classifier training data')
    parser.add_argument('--samples', type=int, default=2000, help='Samples per class')
    parser.add_argument('--augment-llm', action='store_true', help='Enable LLM paraphrase augmentation (requires GROQ_API_KEY)')
    args = parser.parse_args()

    train_df, val_df, test_df = build_dataset(num_samples_per_class=args.samples)

    if args.augment_llm:
        print('\n[*] Running LLM paraphrase augmentation on training set...')
        train_df = augment_dataset_with_llm(train_df, n_paraphrases=3)
        train_df.to_csv(os.path.join('data', 'train.csv'), index=False)
        print(f'[+] Augmented training set saved ({len(train_df)} rows)')
