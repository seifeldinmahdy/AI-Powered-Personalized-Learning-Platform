"""
Tests for the deterministic Code Extractor agent.

Tests:
1. Code detection in text chunks
2. Language identification
3. Code extraction accuracy
4. False positive resistance (English text without code)
"""

import pytest


# ============================================================
# TEST 1: Code detection
# ============================================================

class TestCodeDetection:

    def test_python_code_detected(self):
        """Python code with functions and imports should be detected."""
        from slide_gen.agents.code_extractor import chunk_has_code
        chunk = """
        Here is an example:
        def factorial(n):
            if n <= 1:
                return 1
            return n * factorial(n-1)
        """
        assert chunk_has_code(chunk), "Python function not detected"

    def test_repl_code_detected(self):
        """Python REPL (>>>) should be detected as code."""
        from slide_gen.agents.code_extractor import chunk_has_code
        chunk = """
        Consider the following session:
        >>> x = 5
        >>> print(x + 3)
        8
        """
        assert chunk_has_code(chunk), "Python REPL not detected"

    def test_pure_text_not_detected(self):
        """Pure English text should NOT be flagged as code."""
        from slide_gen.agents.code_extractor import chunk_has_code
        chunk = """
        Computer science is the study of algorithms and data structures.
        Students learn to solve problems using systematic approaches.
        Understanding complexity helps us write efficient programs.
        """
        assert not chunk_has_code(chunk), "Pure text incorrectly flagged as code"

    def test_code_mentions_not_detected(self):
        """Text ABOUT code (but not actual code) should not trigger."""
        from slide_gen.agents.code_extractor import chunk_has_code
        chunk = """
        The concept of a function allows us to encapsulate logic.
        We can call functions to perform specific tasks.
        Variables store values that we can reference later.
        """
        assert not chunk_has_code(chunk), "Code discussion incorrectly flagged"


# ============================================================
# TEST 2: Language identification
# ============================================================

class TestLanguageDetection:

    def test_python_language(self):
        """Python code should be identified as 'python'."""
        from slide_gen.agents.code_extractor import detect_language
        code = "def greet(name):\n    print(f'Hello {name}')\n    return True"
        assert detect_language(code) == "python"

    def test_javascript_language(self):
        """JavaScript code should be identified as 'javascript'."""
        from slide_gen.agents.code_extractor import detect_language
        code = "const greeting = (name) => {\n  console.log(`Hello ${name}`);\n};"
        assert detect_language(code) == "javascript"

    def test_java_language(self):
        """Java code should be identified as 'java'."""
        from slide_gen.agents.code_extractor import detect_language
        code = "public class Main {\n  public static void main(String[] args) {\n    System.out.println('Hello');\n  }\n}"
        assert detect_language(code) == "java"


# ============================================================
# TEST 3: Code extraction
# ============================================================

class TestCodeExtraction:

    def test_extracts_code_block(self):
        """extract_code should return code and language from a mixed chunk."""
        from slide_gen.agents.code_extractor import extract_code
        chunk = """
        A stack follows Last-In-First-Out ordering. Here is a Python example:
        
        class Stack:
            def __init__(self):
                self.items = []
            def push(self, item):
                self.items.append(item)
        
        The stack allows efficient push and pop operations.
        """
        result = extract_code(chunk)
        assert result is not None, "No code extracted from chunk with code"
        assert "language" in result
        assert "code" in result
        assert len(result["code"]) > 10

    def test_no_extraction_from_text(self):
        """extract_code should return None for text-only chunks."""
        from slide_gen.agents.code_extractor import extract_code
        chunk = """
        Data structures help organize information efficiently.
        Choosing the right structure depends on the operations needed.
        Arrays provide constant-time access by index.
        """
        result = extract_code(chunk)
        assert result is None, "Code extracted from text-only chunk"
