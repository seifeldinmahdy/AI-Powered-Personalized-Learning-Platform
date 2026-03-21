import pandas as pd
import random

print("Generating dataset...")

templates = {
    "array": [
        "Write a python function to find the {metric} value in a list.",
        "Create a program that {action} an array of integers.",
        "Write a function to remove all {item} from a list.",
        "How do you return the {metric} element in an array?",
        "Write a python script to count the number of {item} in an array."
    ],
    "math": [
        "Write a python function to calculate the {math_op} of two numbers.",
        "Create a program that checks if a given number is {number_type}.",
        "Write a function to find the area of a {shape}.",
        "How do you write a function to return the {math_op} of a list of numbers?",
        "Create a script to generate a random {number_type} number."
    ],
    "string": [
        "Write a python function to {str_action} a string.",
        "Create a program that counts the number of {char_type} in a word.",
        "Write a function to check if a string is a {str_type}.",
        "How do you {str_action} all the letters in a sentence?",
        "Write a script to remove all {char_type} from a given string."
    ],
    "dictionary": [
        "Write a python function to get all the {dict_part} from a dictionary.",
        "Create a program that merges two dictionaries and {dict_action}.",
        "Write a function to check if a {dict_part} exists in a dictionary.",
        "How do you iterate over all {dict_part} in a hash map?"
    ],
    "loop": [
        "Write a python function to loop through {loop_target} and {loop_action}.",
        "Create a script using a {loop_type} loop to {loop_action}.",
        "How do you use a {loop_type} loop to iterate over {loop_target}?",
        "Write a program that uses a loop to find the {metric} in {loop_target}."
    ],
    "conditional": [
        "Write a function using an if-statement to check if {condition_check}.",
        "Create a program that returns {boolean_val} if {condition_check}.",
        "How do you write a conditional statement to verify if {condition_check}?",
        "Write a python script that prints a message if {condition_check}."
    ],
    "set": [
        "Write a python function to find the {set_operation} of two sets.",
        "Create a script to remove duplicate {item} by converting a list to a set.",
        "How do you check if one set is a subset of another?",
        "Write a function to add multiple {item} to an existing set."
    ],
    "tuple": [
        "Write a python function to unpack a tuple containing {tuple_content}.",
        "How do you return multiple {tuple_content} from a function using a tuple?",
        "Create a program that finds the {metric} value inside a tuple of numbers.",
        "Write a script to convert a tuple into a list to modify its {item}."
    ]
}

# 2. Expanded Vocabulary to Fill the Blanks
fillers = {
    # Existing Arrays & Math
    "metric": ["maximum", "minimum", "average", "median", "first", "last", "most frequent", "second largest"],
    "action": ["sorts", "reverses", "shuffles", "clears", "copies", "prints", "flattens"],
    "item": ["duplicates", "negative numbers", "zeros", "even numbers", "odd numbers", "empty strings", "None values"],
    "math_op": ["sum", "difference", "product", "quotient", "remainder", "square root", "absolute value"],
    "number_type": ["prime", "even", "odd", "positive", "negative", "whole", "decimal", "floating-point"],
    "shape": ["circle", "square", "rectangle", "triangle", "cube", "cylinder"],
    
    # Existing Strings & Dicts
    "str_action": ["reverse", "capitalize", "lowercase", "uppercase", "split", "join", "strip whitespace from"],
    "char_type": ["vowels", "consonants", "spaces", "digits", "special characters", "punctuation marks"],
    "str_type": ["palindrome", "valid email", "valid password", "pangram", "anagram"],
    "dict_part": ["keys", "values", "items", "nested keys"],
    "dict_action": ["sums the values", "removes duplicates", "sorts by key", "prints the output", "inverts the keys and values"],
    
    # NEW: Loops
    "loop_target": ["a list of numbers", "a string", "a dictionary's keys", "a range of integers", "a 2D matrix"],
    "loop_action": ["print each element", "sum the values", "count the items", "filter out negative numbers", "append them to a new list"],
    "loop_type": ["for", "while", "nested for"],
    
    # NEW: Conditionals & Booleans
    "condition_check": ["a number is even", "a string is empty", "a list contains a specific value", "two variables are equal", "a dictionary has a specific key", "a user is over 18"],
    "boolean_val": ["True", "False"],
    
    # NEW: Sets & Tuples
    "set_operation": ["union", "intersection", "difference", "symmetric difference"],
    "tuple_content": ["X and Y coordinates", "RGB color values", "student names and grades", "min and max values"]
}

# 3. Generate the data
training_data = []

# We will generate 30,000 perfect rows (Neural networks like a bit of repetition for grammar)
target_rows = 30000

for _ in range(target_rows):
    # Pick a random topic
    topic = random.choice(list(templates.keys()))
    
    # Pick a random template for that topic
    template = random.choice(templates[topic])
    
    # Fill in the blanks with random vocabulary
    try:
        question = template.format(**{k: random.choice(v) for k, v in fillers.items()})
    except KeyError:
        continue # Skip if there's a formatting mismatch
        
    training_data.append({
        "input_topic": f"generate {topic}",
        "target_question": question
    })

# Save to CSV
df = pd.DataFrame(training_data)

# Shuffle the data so it's not all in order
df = df.sample(frac=1).reset_index(drop=True)

df.to_csv("clean_coding_questions.csv", index=False)

print(f"✅ Success! Generated {len(df)} perfect, simple coding questions.")
print("\nSample rows:")
print(df.head(10))