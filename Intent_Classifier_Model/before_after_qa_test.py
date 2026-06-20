"""Before/after QA-testing classification sanity check."""
import torch
from TinyBert import IntentClassifier

INTENT_NAMES = [
    'On-Topic Question', 'Off-Topic Question', 'Emotional-State',
    'Pace-Related', 'Repeat/clarification', 'Debugging/Code-Sharing',
]

QA_UTTERANCES = [
    # Clear examples
    ("How do I write a unit test for a simple function?", "On-Topic Question"),
    ("What is boundary value analysis and why does it matter?", "On-Topic Question"),
    ("Can you show me an example of pytest fixtures?", "On-Topic Question"),
    ("What's the weather like today?", "Off-Topic Question"),
    ("I'm so confused by all these testing terms", "Emotional-State"),
    ("This is really frustrating", "Emotional-State"),
    ("Can we slow down a bit?", "Pace-Related"),
    ("You're going too fast", "Pace-Related"),
    ("Can you repeat that part about mock objects?", "Repeat/clarification"),
    ("What did you say about test coverage?", "Repeat/clarification"),
    ("my test keeps failing with AssertionError, here's my code `def test_add(): assert add(2,2)==5`", "Debugging/Code-Sharing"),
    ("I get `NameError: name 'fixture' is not defined` when running pytest", "Debugging/Code-Sharing"),
    # Ambiguous examples where QA context should disambiguate
    ("Can you explain that again?", "Repeat/clarification"),
    ("I don't get it", "Emotional-State"),
    ("Wait", "Pace-Related"),
    ("What about this?", "On-Topic Question"),
    ("Again?", "Repeat/clarification"),
    ("I'm lost", "Emotional-State"),
]

QA_CONTEXTS = [
    "topic:Unit Testing | prev:Introduction to Testing | ability:Novice | emotion:neutral | pace:normal | slides:5,6,7",
    "topic:pytest Fixtures | prev:Setup and Teardown | ability:Novice | emotion:confused | pace:normal | slides:12,13,14",
    "topic:Boundary Value Analysis | prev:Equivalence Partitioning | ability:Novice | emotion:frustrated | pace:fast | slides:20,21,22",
]


def evaluate(model_path: str):
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    clf = IntentClassifier(
        num_classes=6,
        bert_model_name='distilbert-base-uncased',
        device=device,
    )
    clf.load_model(model_path)
    print(f"\nModel: {model_path} | Device: {device}")
    print("-" * 90)

    correct = 0
    total = 0
    for text, expected in QA_UTTERANCES:
        ctx = QA_CONTEXTS[total % len(QA_CONTEXTS)]
        preds, probs = clf.predict([text], [ctx])
        pred_id = preds[0]
        conf = float(probs[0][pred_id])
        pred_name = INTENT_NAMES[pred_id]
        match = "OK" if pred_name == expected else "XX"
        if pred_name == expected:
            correct += 1
        total += 1
        print(f"{match} {pred_name:26} ({conf:.2f})  expected={expected:26}  {text[:55]}")

    print("-" * 90)
    print(f"QA accuracy: {correct}/{total} = {correct/total:.2%}")
    return correct / total


if __name__ == "__main__":
    import sys
    model_path = sys.argv[1] if len(sys.argv) > 1 else "best_model.pt"
    evaluate(model_path)
