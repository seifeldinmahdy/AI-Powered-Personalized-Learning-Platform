# MCQ Model Evaluation Report

## Section 1 — Overall Statistics

| Metric | Value |
|---|---|
| Total generations attempted | 360 |
| Parse successes | 293 (81.4%) |
| Parse failures | 67 (18.6%) |
| DG successes (3 real distractors) | 293 (81.4%) |
| Format issues | 36 (10.0%) |
| Conditioning failures (very_weak → non-4a) | 41 |
| Generation time min | 2.6s |
| Generation time max | 17.3s |
| Generation time mean | 7.1s |
| Generation time p95 | 12.4s |
| Avg distractor similarity | 0.5225 |

### Parse Failure Examples

```
--- Condition: Novice × very_weak × no misconception ---
Error: QG parse failed
Raw output (first 300 chars): QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(8, 5))
axes = plt.subplot(111)
n = 5
Z = np.zeros((n, 4))
X = np.linspace(0, 2, n)
Y = np.random.random((n, 4))
plt.boxplot(Y)
plt.xticks([])
p

--- Condition: Novice × moderate × no misconception ---
Error: QG parse failed
Raw output (first 300 chars): QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(8, 5))
axes = plt.subplot(111)
n = 5
Z = np.zeros((n, 4))
X = np.linspace(0, 2, n)
Y = np.random.random((n, 4))
plt.boxplot(Y)
plt.xticks([])
p

--- Condition: Novice × strong × no misconception ---
Error: QG parse failed
Raw output (first 300 chars): QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(8, 5))
axes = plt.subplot(111)
n = 5
Z = np.zeros((n, 4))
X = np.linspace(0, 2, n)
Y = np.random.random((n, 4))
plt.boxplot(Y)
plt.xticks([])
p

--- Condition: Intermediate × very_weak × no misconception ---
Error: QG parse failed
Raw output (first 300 chars): QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(8, 5))
axes = plt.subplot(111)
n = 5
Z = np.zeros((n, 4))
X = np.linspace(0, 2, n)
Y = np.random.random((n, 4))
plt.boxplot(Y)
plt.xticks([])
p

--- Condition: Intermediate × moderate × no misconception ---
Error: QG parse failed
Raw output (first 300 chars): QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(figsize=(8, 5))
axes = plt.subplot(111)
n = 5
Z = np.zeros((n, 4))
X = np.linspace(0, 2, n)
Y = np.random.random((n, 4))
plt.boxplot(Y)
plt.xticks([])
p

```

## Section 2 — Personalization Signal Analysis

### Mastery Level Effect

| Mastery | Avg Cognitive Level | n |
|---|---|---|
| Novice | 1.71 | 51 |
| Intermediate | 1.74 | 42 |
| Expert | 3.13 | 45 |

#### Vocabulary Complexity by Mastery

| Mastery | Avg Word Length | Avg Words/Sentence |
|---|---|---|
| Novice | 5.78 | 13.7 |
| Intermediate | 5.35 | 11.0 |
| Expert | 5.26 | 17.7 |

#### Novice vs Expert Examples (same chunk)

**Chunk:** `The urllib library uses the socket library to make the actual network connection...`

- **Novice (cog=1):** According to the passage, what is returned by the `html.parser` object in BeautifulSoup?
- **Expert (cog=4):** You are analyzing a program that uses the urllib library to retrieve data from a website and then passes this data to BeautifulSoup for parsing. Which statement best captures why the program is able t
- **Result:** ✅ Differentiated

**Chunk:** `Performance of Python Data Structures 55 Problem Solving with Algorithms and Dat...`

- **Novice (cog=2):** Which method removes and returns the last element of a Python list?
- **Expert (cog=3):** Consider the following code snippet:
```python
d = {}
for i in range(1000):
    d[i] = None
print(d[500])
```
OUTPUT:
```
None
```
- **Result:** ✅ Differentiated

**Chunk:** `You can use the dictionary from Exercise 11.1 to check whether a string is in th...`

- **Novice (cog=2):** Which method is used to check whether a string is in the word list?
```python
word_list = ['hello', 'world', 'foo']
string_to_check = 'bar'
if string_to_check in word_list:
    print(string_to_check, 
- **Expert (cog=3):** You have a list of words that you want to check against a dictionary of pronunciations. Write a program that uses the `read_dictionary` function from the `pronounce.py` module to create a dictionary a
- **Result:** ✅ Differentiated


### Score Category Override Effect

**very_weak → Type 4a adherence:** 5/46 (10.9%)

| Type Produced | Count |
|---|---|
| Type 1 | 26 |
| Type 2 | 10 |
| Type 4a | 5 |
| Type 4d | 5 |

#### Override Failures (very_weak producing non-4a)

- **Intermediate × very_weak → Type 1**
  Chunk: `The urllib library uses the socket library to make the actual network connection...`
  Question: In the code snippet below, which method is called on the `html.parser` object to retrieve a dictionary of tag objects?
```python
from bs4 import Beaut
- **Expert × very_weak → Type 4d**
  Chunk: `The urllib library uses the socket library to make the actual network connection...`
  Question: You are analyzing a program that uses the urllib library to retrieve data from a website and then passes this data to BeautifulSoup for parsing. Which
- **Novice × very_weak → Type 1**
  Chunk: `Performance of Python Data Structures 55 Problem Solving with Algorithms and Dat...`
  Question: Which method removes and returns the last element of a Python list?
- **Intermediate × very_weak → Type 1**
  Chunk: `Performance of Python Data Structures 55 Problem Solving with Algorithms and Dat...`
  Question: Which method is used to remove and return the last element of a Python list?
```python
list.pop()
list.pop(0)
list.pop(len(list) - 1)
```
- **Expert × very_weak → Type 2**
  Chunk: `Performance of Python Data Structures 55 Problem Solving with Algorithms and Dat...`
  Question: Consider the following code snippet:
```python
d = {}
for i in range(1000):
    d[i] = None
print(d[500])
```
OUTPUT:
```
None
```

#### Override adherence by mastery level

| Mastery | Total very_weak | Produced 4a | Rate |
|---|---|---|---|
| Novice | 17 | 5 | 29.4% |
| Intermediate | 14 | 0 | 0.0% |
| Expert | 15 | 0 | 0.0% |

### Question Type Forcing Effect (Axis 2)

| Forced Type | Cognitive Level | Total | Matched | Adherence Rate |
|---|---|---|---|---|
| Type 4a | 1 | 18 | 15 | 83.3% |
| Type 4b | 2 | 19 | 18 | 94.7% |
| Type 4c | 3 | 18 | 10 | 55.6% |
| Type 4d | 4 | 20 | 19 | 95.0% |
| Type 4e | 4 | 19 | 19 | 100.0% |

#### Type Confusion Examples

- **Forced Type 4c (expected cog=3) → detected cog=4**
  Q: A student claims that Python's built-in functions, such as len() and str.split(), are implemented by calling external libraries or modules. Which statement correctly distinguishes this claim from the 
- **Forced Type 4c (expected cog=3) → detected cog=1**
  Q: You have implemented a recursive function named `factorial` that takes an integer as input and returns its factorial. However, you notice that the function occasionally runs into an infinite recursion
- **Forced Type 4d (expected cog=4) → detected cog=1**
  Q: You are analyzing a program that uses polymorphism to add Time objects together. The program contains two functions, `add_time` and `sum_times`, which use the built-in `sum` function to calculate the 
- **Forced Type 4c (expected cog=3) → detected cog=4**
  Q: You have written a program to compute the average of a list of numbers, and you want to add an additional "sanity check" to ensure that the result is within reasonable bounds. Which statement best des
- **Forced Type 4c (expected cog=3) → detected cog=4**
  Q: You are writing an infinite loop for countdown and want to break out of it when n reaches 0. Which statement correctly explains why you need to use the `break` statement?

### Misconception Context Effect (Axis 3)

- Questions **without** misconception context: 14
- Questions **with** misconception context: 47
- Misconception targeting success (no fallback needed): 34/47

#### Side-by-Side Comparisons

**Chunk:** `The urllib library uses the socket library to make the actual network connection...`

- **No misconception:** In the code snippet below, which method is called on the `html.parser` object to retrieve a dictionary of tag objects?
```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(html_string, 'html.p
- **With misconception:** Which method is called on the returned object from BeautifulSoup to retrieve a dictionary of tag objects?
- **Result:** ✅ Question changed

**Chunk:** `The urllib library uses the socket library to make the actual network connection...`

- **No misconception:** In the code snippet below, which method is called on the `html.parser` object to retrieve a dictionary of tag objects?
```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(html_string, 'html.p
- **With misconception:** Which method is called on the returned object from BeautifulSoup to retrieve a dictionary of tag objects?
- **Result:** ✅ Question changed

**Chunk:** `The urllib library uses the socket library to make the actual network connection...`

- **No misconception:** In the code snippet below, which method is called on the `html.parser` object to retrieve a dictionary of tag objects?
```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(html_string, 'html.p
- **With misconception:** Which method is called on the returned object from BeautifulSoup to retrieve a dictionary of tag objects?
- **Result:** ✅ Question changed


## Section 3 — Distractor Quality Analysis

**Average distractor plausibility:** 0.5225

| Mastery | Avg Distractor Similarity | n |
|---|---|---|
| Novice | 0.5164 | 153 |
| Intermediate | 0.5127 | 309 |
| Expert | 0.5320 | 417 |

- Low similarity distractors (<0.35): 235 (26.7%)
- High similarity distractors (>0.70): 255 (29.0%)

#### Best Distractors (sim > 0.7)

- **sim=1.000** | Correct: `x = 5` → Distractor: `x=5`
- **sim=1.000** | Correct: `x = 5` → Distractor: `x=5`
- **sim=0.991** | Correct: `log * p(X) 1 −p(X) + = β0 + β1X1 + · · · + βpXp` → Distractor: `log * p(X) 1 −p(X) = β0 + β1X1 + · · · + βpXp`
- **sim=0.983** | Correct: `import pronounce read_dict = pronounce.read_dictionary() words_to_check = ['hell` → Distractor: `import pronounce read_dict = pronounce.read_dictionary() words_to_check = ['hell`
- **sim=0.983** | Correct: `import pronounce read_dict = pronounce.read_dictionary() words_to_check = ['hell` → Distractor: `import pronounce read_dict = pronounce.read_dictionary() words_to_check = ['hell`

#### Worst Distractors (sim < 0.3)

- **sim=0.001** | Correct: `model.fit(X_train, y_train, epochs=10)` → Distractor: `None of the above`
- **sim=0.001** | Correct: `model.fit(X_train, y_train, epochs=10)` → Distractor: `None of the above`
- **sim=0.001** | Correct: ``cv_mse.append(errors.mean(0))`` → Distractor: `None of the above`
- **sim=0.001** | Correct: ``cv_mse.append(errors.mean(0))`` → Distractor: `None of the above`
- **sim=0.010** | Correct: `The `stack` is popped and the error is ignored.` → Distractor: `All of the above`

**Average pairwise distractor similarity:** 0.5073
**Low diversity sets (pairwise > 0.85):** 12

#### Low Diversity Examples

- Q: `Which statement correctly distinguishes the role of **html.parser** from that of **urllib** in the p...`
  D1: `html.parser is responsible for handling network requests, whereas urllib is solely used for parsing HTML.`
  D2: `Both html.parser and urllib retrieve data from external URLs; they merely differ in how that data is processed afterwards.`
  D3: `Both html_parser and urllib fetch external resources; they merely differ in their protocols (e.g., HTTP vs HTTPS).`
  Pairwise sim: 0.852

- Q: `In Python, what is the syntax to create a tuple?...`
  D1: ``my_tuple = value1 + value2``
  D2: ``my_tuple = value1 value2``
  D3: ``my_tuple = value1, value2``
  Pairwise sim: 0.976

- Q: `You have a list of words that you want to check against a dictionary of pronunciations. Write a prog...`
  D1: `read_dict = pronounce.read_dictionary() for word in words_to_check: if word in read_dict: print(f'"{word}" is pronounced correctly')`
  D2: `import pronounce read_dict = pronounce.read_dictionary() words_to_check = ['hello', 'world'] for word in words_to_check: print(f'"{word}"')`
  D3: `import pronounce read_dict = pronounce.read_pronunciations() words_to_check = ['hello', 'world'] for word in words_to_check: print(f'"{word}" is pronounced correctly')`
  Pairwise sim: 0.943

## Section 4 — Failure Mode Catalog

| Failure Mode | Count | % of Total |
|---|---|---|
| parse_failure | 67 | 18.6% |
| cognitive_level_mismatch | 50 | 13.9% |
| fallback_distractor_used | 36 | 10.0% |

### fallback_distractor_used

```
Q: You are building a program that uses the urllib library to retrieve data from a website and then pas... | A: socket
Q: Which method removes and returns the last element of a Python list?... | A: .pop()
Q: Which method removes and returns the last element of a Python list?... | A: .pop()
```

### cognitive_level_mismatch

```
Type 1: expected=2 got=1 | Q: In Python, what is the syntax to create a tuple?
Type 1: expected=2 got=1 | Q: In Python, what is the syntax to create a tuple?
Type 1: expected=2 got=1 | Q: In Python, what is the syntax to create a tuple?
```

### parse_failure

```
Condition: Novice × very_weak × no misconception | Error: QG parse failed | Raw: QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(fi
Condition: Novice × moderate × no misconception | Error: QG parse failed | Raw: QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(fi
Condition: Novice × strong × no misconception | Error: QG parse failed | Raw: QUESTION: In the following code snippet from the Scipy lecture notes:
```python
import numpy as np
import matplotlib.pyplot as plt
fig = plt.figure(fi
```

## Section 5 — Content Type Performance

| Content Type | Total | Parse Success | Avg Distractor Sim | Format Issues |
|---|---|---|---|---|
| definition | 54 | 81.5% | 0.5180 | 5 |
| code | 144 | 68.8% | 0.5200 | 13 |
| comparison | 18 | 100.0% | 0.4289 | 0 |
| causal | 108 | 88.9% | 0.5338 | 11 |
| procedural | 36 | 100.0% | 0.5513 | 7 |

**Best performing:** procedural (avg sim: 0.5513)
**Worst performing:** comparison (avg sim: 0.4289)

## Section 6 — Specific Recommendations For The Next Training Run

### Recommendation 1

**PROBLEM:** QG parse failures: 67/360 generations failed to parse
**FREQUENCY:** 18.6%
**ROOT CAUSE HYPOTHESIS:** Model not reliably following QUESTION/ANSWER/EXPLANATION output format

**RECOMMENDED FIX:**
- Data generation: Add output format reinforcement examples — include 50+ examples with explicit format headers
- Training format: Add format compliance token in format_qg.py as a separate training signal
- Prompt: Add explicit negative examples in system prompt: 'Do NOT output JSON. Do NOT output markdown fences.'
- Model/PEFT: Consider increasing num_predict from 256 to 384 if truncation is causing parse failures

**EXPECTED IMPACT:** Should reduce parse failure rate from 18.6% toward <2%

### Recommendation 2

**PROBLEM:** Format contamination: 36 questions have format issues (top: fallback_distractor_used=36)
**FREQUENCY:** 10.0%
**ROOT CAUSE HYPOTHESIS:** Training data still contains option labels, letter prefixes from raw teacher LLM output

**RECOMMENDED FIX:**
- Data generation: Run clean_dataset.py with stricter validation; add regex check for A/B/C/D in question stem
- Training format: In format_qg.py: add post-processing to strip any residual option labels before creating training example
- Prompt: No prompt changes needed — this is a data quality issue
- Model/PEFT: No model changes needed

**EXPECTED IMPACT:** Should eliminate the 10.0% format issue rate

### Recommendation 3

**PROBLEM:** very_weak score category not reliably forcing Type 4a: 41 failures
**FREQUENCY:** 41/46 very_weak conditions
**ROOT CAUSE HYPOTHESIS:** Insufficient very_weak training examples; selector correctly forces 4a but model ignores the type conditioning

**RECOMMENDED FIX:**
- Data generation: Increase very_weak × 4a examples to at least 200 in training data. Currently underrepresented.
- Training format: No changes needed — format_qg correctly passes score_category in the prompt
- Prompt: Add explicit instruction: 'When score_category is very_weak, you MUST generate a definition/recall question regardless of other signals.'
- Model/PEFT: Consider increasing LoRA rank from 16 to 32 if conditioning adherence doesn't improve with more data

**EXPECTED IMPACT:** Should improve very_weak → 4a adherence from current to >95%

### Recommendation 4

**PROBLEM:** DG model failing to produce enough unique distractors: 36 questions needed fallback padding
**FREQUENCY:** 10.0%
**ROOT CAUSE HYPOTHESIS:** DG model sometimes outputs the correct answer or duplicates instead of unique wrong answers

**RECOMMENDED FIX:**
- Data generation: Ensure each DG training example has a distractor that is clearly wrong but semantically related
- Training format: In format_dg.py: filter out training examples where distractor is too similar to correct answer (cosine > 0.95)
- Prompt: Add: 'The distractor MUST be factually wrong. It MUST NOT be a rephrasing of the correct answer.'
- Model/PEFT: DG may need more training examples per distractor type; currently 3x multiplier may not be enough for all types

**EXPECTED IMPACT:** Should reduce fallback usage from 10.0% to <5%

### Recommendation 5

**PROBLEM:** Low distractor diversity: 12 questions have pairwise sim > 0.85
**FREQUENCY:** 3.3%
**ROOT CAUSE HYPOTHESIS:** DG model generating variations of the same wrong concept rather than targeting distinct misconceptions

**RECOMMENDED FIX:**
- Data generation: In data_generator.py: ensure training distractors cover 3 different misconception categories per question
- Training format: Add a 'distractor_type' field (e.g., 'definitional_error', 'scope_error', 'syntax_confusion') to DG training data
- Prompt: Add: 'This distractor must target a DIFFERENT misconception than previous distractors.'
- Model/PEFT: Consider temperature > 0.8 for DG or nucleus sampling to increase output diversity

**EXPECTED IMPACT:** Should reduce low-diversity sets from 12 to near 0

### Recommendation 6

**PROBLEM:** Data distribution balance across all conditioning signals
**FREQUENCY:** Structural recommendation (not a failure)
**ROOT CAUSE HYPOTHESIS:** Training data may have imbalanced representation across mastery × score_category × type combinations

**RECOMMENDED FIX:**
- Data generation: Target minimums per combination: Novice×very_weak: 100, Novice×moderate: 100, Novice×strong: 100, Intermediate×very_weak: 100, Intermediate×moderate: 150, Intermediate×strong: 100, Expert×very_weak: 80, Expert×moderate: 100, Expert×strong: 120. Code question types (1,2,3): at least 150 each. Conceptual types (4a-4e): at least 200 each.
- Training format: Use cap_dataset.py and merge_dataset.py to enforce these minimums
- Prompt: No changes needed
- Model/PEFT: With balanced data, current LoRA r=16 should be sufficient for 3B model

**EXPECTED IMPACT:** Balanced data ensures conditioning adherence across all signal combinations

### Recommendation 7

**PROBLEM:** QG vs DG failure comparison: QG parse fail=18.6%, DG incomplete=18.6%
**FREQUENCY:** N/A
**ROOT CAUSE HYPOTHESIS:** QG and DG have independent failure modes; poor QG output cascades to DG failures

**RECOMMENDED FIX:**
- Data generation: Focus on QG quality first — a bad question makes DG impossible regardless of DG model quality
- Training format: No changes needed
- Prompt: No changes needed
- Model/PEFT: If QG is the bottleneck, allocate more training epochs to QG (5 epochs) vs DG (3 epochs)

**EXPECTED IMPACT:** Fixing QG should reduce overall pipeline failure rate

## Section 7 — Priority-Ordered Action List

1. **QG parse failures**
   - What: Add output format reinforcement examples — include 50+ examples with explicit format headers
   - Expected improvement: Should reduce parse failure rate from 18.6% toward <2%
2. **Format contamination**
   - What: Run clean_dataset.py with stricter validation; add regex check for A/B/C/D in question stem
   - Expected improvement: Should eliminate the 10.0% format issue rate
3. **very_weak score category not reliably forcing Type 4a**
   - What: Increase very_weak × 4a examples to at least 200 in training data. Currently underrepresented.
   - Expected improvement: Should improve very_weak → 4a adherence from current to >95%
4. **DG model failing to produce enough unique distractors**
   - What: Ensure each DG training example has a distractor that is clearly wrong but semantically related
   - Expected improvement: Should reduce fallback usage from 10.0% to <5%
5. **Low distractor diversity**
   - What: In data_generator.py: ensure training distractors cover 3 different misconception categories per question
   - Expected improvement: Should reduce low-diversity sets from 12 to near 0
6. **Data distribution balance across all conditioning signals**
   - What: Target minimums per combination: Novice×very_weak: 100, Novice×moderate: 100, Novice×strong: 100, Intermediate×very_weak
   - Expected improvement: Balanced data ensures conditioning adherence across all signal combinations
7. **QG vs DG failure comparison**
   - What: Focus on QG quality first — a bad question makes DG impossible regardless of DG model quality
   - Expected improvement: Fixing QG should reduce overall pipeline failure rate
