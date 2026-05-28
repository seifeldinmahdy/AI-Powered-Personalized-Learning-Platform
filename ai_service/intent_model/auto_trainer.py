import os
import json
import shutil
import subprocess
import time

STATE_FILE = "pipeline_state.json"
RETRAIN_THRESHOLD = 50
MODEL_PROD_PATH = "prod_tinybert.pt"
MODEL_NEW_STAGE_PATH = "best_tinybert.pt"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"sessions_since_last_train": 0, "total_sessions": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def run_training_pipeline():
    print("\n" + "=" * 50)
    print(">>> Auto-Trainer: Triggering Retraining Pipeline")
    print("=" * 50)

    print("\n[Step 0] Checking real utterance dataset...")
    real_path = os.path.join(os.path.dirname(__file__), 'data', 'real_utterances.csv')
    real_stale = (
        not os.path.exists(real_path) or
        (time.time() - os.path.getmtime(real_path)) > 7 * 24 * 3600  # older than 7 days
    )
    if real_stale:
        print("[Step 0] Regenerating real utterances (Groq)...")
        result = subprocess.run(
            ["python", "generate_real_utterances.py", "--per-class", "50"],
            capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode != 0:
            print("[!] Real utterance generation failed (non-fatal):")
            print(result.stderr[:500])
        else:
            print(f"[+] Real utterances ready at {real_path}")
    else:
        print(f"[+] Real utterances up to date: {real_path}")
    
    print("\n[Step 1] Running data generation (dataset_generator.py)...")
    result = subprocess.run(["python", "dataset_generator.py"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print("[!] Data pipeline failed:")
        print(result.stderr)
        return False
    print("[+] Data pipeline finished.")
    
    print("\n[Step 2] Running training (train.py)...")
    result = subprocess.run(["python", "train.py"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print("[!] Training failed:")
        print(result.stderr)
        return False
    print("[+] Training finished.")
    
    print("\n[Step 3] Validating model quality...")
    if os.path.exists('training_results.json'):
        with open('training_results.json', 'r') as f:
            results = json.load(f)
            metrics = results.get("metrics", {})
            acc = metrics.get("accuracy", 0.0)
            f1 = metrics.get("f1_score", 0.0)
            
            print(f"New model validation: Accuracy={acc*100:.2f}%, F1={f1*100:.2f}%")
            
            # Per-class quality floor: reject if Emotional-State F1 is too low
            per_class = results.get("per_class_metrics", {})
            emotional_f1 = per_class.get("Emotional-State", {}).get("f1_score", 0.0)
            
            # Validation logic:
            # 1. Must meet minimum quality bar (80% acc, 80% F1)
            # 2. Perfect 100% on test set = pure memorization (reject)
            # 3. Per-class floor: Emotional-State F1 >= 0.75
            if acc >= 1.0:
                print(f"[!] Perfect 100% test accuracy. Likely memorization. Rejecting model.")
                return False
            elif acc >= 0.80 and f1 >= 0.80 and emotional_f1 >= 0.75:
                print(f"[+] Metrics meet quality bar (emotional_f1={emotional_f1:.3f}). Promoting model to production.")
                if os.path.exists(MODEL_NEW_STAGE_PATH):
                    shutil.copy(MODEL_NEW_STAGE_PATH, MODEL_PROD_PATH)
                    print(f"[+] Model published to {MODEL_PROD_PATH}")
                    return True
            else:
                print(f"[!] Quality bar not met (acc={acc:.3f}, f1={f1:.3f}, emotional_f1={emotional_f1:.3f}). Rejecting model.")
                return False
    else:
        print("[!] Could not find training_results.json.")
        return False

def add_session_and_check():
    state = load_state()
    state["sessions_since_last_train"] += 1
    state["total_sessions"] += 1
    
    print(f"Logged new session. (Total since train: {state['sessions_since_last_train']})")
    
    if state["sessions_since_last_train"] >= RETRAIN_THRESHOLD:
        print("\nThreshold reached! Starting training pipeline...")
        success = run_training_pipeline()
        
        if success:
            state["sessions_since_last_train"] = 0
            print("Resetting sessions counter.")
        else:
            print("Retaining count. Will try again on next session.")
            
    save_state(state)
    return state

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--force-train":
        run_training_pipeline()
    else:
        add_session_and_check()
