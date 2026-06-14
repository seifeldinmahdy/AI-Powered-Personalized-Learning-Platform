"""
Auto-trainer state manager and retraining pipeline trigger.
Counts sessions since last retrain, triggers the full pipeline when the
threshold is reached, and promotes the new model to production on success.
"""
import os
import json
import time
import shutil
import subprocess

STATE_FILE            = "pipeline_state.json"
RETRAIN_THRESHOLD     = 50
MODEL_PROD_PATH       = "prod_tinybert.pt"
MODEL_NEW_STAGE_PATH  = "best_model.pt"
REAL_UTTERANCES_PATH  = os.path.join("data", "real_utterances.csv")
REAL_UTTERANCES_MAX_AGE_DAYS = 7


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"sessions_since_last_train": 0, "total_sessions": 0}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _real_utterances_stale() -> bool:
    if not os.path.exists(REAL_UTTERANCES_PATH):
        return True
    age_days = (time.time() - os.path.getmtime(REAL_UTTERANCES_PATH)) / 86400
    return age_days > REAL_UTTERANCES_MAX_AGE_DAYS


def run_training_pipeline() -> bool:
    print("\n" + "=" * 60)
    print(">>> Auto-Trainer: Triggering Retraining Pipeline")
    print("=" * 60)

    # Step 0 — real utterances
    print("\n[Step 0] Checking real utterance dataset...")
    if _real_utterances_stale():
        print("[Step 0] Regenerating real utterances (Groq)...")
        result = subprocess.run(
            ["python", "generate_real_utterances.py", "--per-class", "50"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode != 0:
            print(f"[!] Real utterance generation failed (non-fatal):\n{result.stderr[:400]}")
        else:
            print(f"[+] Real utterances ready at {REAL_UTTERANCES_PATH}")
    else:
        print("[+] Real utterances up to date.")

    # Step 1 — data generation
    print("\n[Step 1] Running dataset_generator.py ...")
    result = subprocess.run(
        ["python", "dataset_generator.py"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"[!] Data pipeline failed:\n{result.stderr}")
        return False
    print("[+] Data pipeline finished.")

    # Step 2 — training
    print("\n[Step 2] Running train.py ...")
    result = subprocess.run(
        ["python", "train.py"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"[!] Training failed:\n{result.stderr}")
        return False
    print("[+] Training finished.")

    # Step 3 — quality gate
    print("\n[Step 3] Validating model quality...")
    if not os.path.exists("training_results.json"):
        print("[!] training_results.json not found.")
        return False

    with open("training_results.json", "r") as f:
        results = json.load(f)

    metrics     = results.get("metrics", {})
    per_class   = results.get("per_class_metrics", {})
    acc         = metrics.get("accuracy", 0.0)
    f1          = metrics.get("f1_score", 0.0)
    emo_f1      = per_class.get("Emotional-State",        {}).get("f1_score", 0.0)
    ontopic_f1  = per_class.get("On-Topic Question",       {}).get("f1_score", 0.0)
    debug_f1    = per_class.get("Debugging/Code-Sharing",  {}).get("f1_score", 0.0)

    print(f"  acc={acc:.3f}  f1={f1:.3f}  "
          f"emotional={emo_f1:.3f}  ontopic={ontopic_f1:.3f}  debug={debug_f1:.3f}")

    if acc >= 1.0:
        print("[!] Perfect accuracy — likely memorisation. Rejecting.")
        return False
    elif (acc >= 0.88 and f1 >= 0.88
          and emo_f1 >= 0.88 and ontopic_f1 >= 0.82 and debug_f1 >= 0.90):
        print("[+] Quality bar met. Promoting model to production.")
        if os.path.exists(MODEL_NEW_STAGE_PATH):
            shutil.copy(MODEL_NEW_STAGE_PATH, MODEL_PROD_PATH)
            print(f"[+] Model published to {MODEL_PROD_PATH}")
        return True
    else:
        print("[!] Quality bar not met. Rejecting.")
        return False


def add_session_and_check() -> dict:
    state = load_state()
    state["sessions_since_last_train"] += 1
    state["total_sessions"]            += 1
    print(f"Session logged. ({state['sessions_since_last_train']} since last train)")

    if state["sessions_since_last_train"] >= RETRAIN_THRESHOLD:
        print("\nThreshold reached. Starting pipeline...")
        success = run_training_pipeline()
        if success:
            state["sessions_since_last_train"] = 0
            print("Counter reset.")
        else:
            print("Retaining count — will retry next session.")

    save_state(state)
    return state


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--force-train":
        run_training_pipeline()
    else:
        add_session_and_check()
