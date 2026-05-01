import os
import json
import shutil
import subprocess

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
            metrics = results.get("real_utterance_metrics") or results.get("metrics", {})
            metric_source = 'real_utterance_metrics' if 'real_utterance_metrics' in results else 'metrics'
            acc = metrics.get("accuracy", 0.0)
            f1 = metrics.get("f1_score", 0.0)
            
            print(f"New model validation ({metric_source}): Accuracy={acc*100:.2f}%, F1={f1*100:.2f}%")
            
            # Validation logic:
            # 1. Prefer real-utterance metrics when available.
            # 2. Perfect 100% on test set = pure memorization (reject)
            if acc >= 1.0:
                print(f"[!] Perfect 100% test accuracy. Likely memorization. Rejecting model.")
                return False
            elif acc >= 0.80 and f1 >= 0.80:
                print(f"[+] Metrics meet quality bar. Promoting model to production.")
                if os.path.exists(MODEL_NEW_STAGE_PATH):
                    shutil.copy(MODEL_NEW_STAGE_PATH, MODEL_PROD_PATH)
                    print(f"[+] Model published to {MODEL_PROD_PATH}")
                    return True
            else:
                print(f"[!] Metrics below quality bar. Rejecting model.")
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
