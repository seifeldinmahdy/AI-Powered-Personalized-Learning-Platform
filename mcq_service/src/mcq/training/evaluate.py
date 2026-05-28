"""Standalone evaluation — model metrics + personalization experiments.

Usage::

    python -m mcq.training.evaluate \\
        --qg-model models/mcq_qg/final \\
        --dg-model models/mcq_dg/final \\
        --test-data data/mcq_training/mcq_raw.jsonl \\
        --output reports/mcq_evaluation.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import structlog
import torch
from sklearn.metrics.pairwise import cosine_similarity
from transformers import T5ForConditionalGeneration, T5Tokenizer

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_test_data(path: str) -> list[dict]:
    samples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return samples


def _get_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def _generate_text(model, tokenizer, input_text, device, max_new=128):
    inputs = tokenizer(input_text, return_tensors="pt", max_length=512, truncation=True).to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new, num_beams=4, early_stopping=True)
    return tokenizer.decode(out[0], skip_special_tokens=True)


# ═══════════════════════════════════════════════════════════════════════════════
# QG EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_qg(model_path: str, test_data_path: str) -> dict:
    """Evaluate QG model: BLEU, ROUGE, per-type breakdown."""
    from rouge_score import rouge_scorer
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = T5Tokenizer.from_pretrained(model_path)
    model = T5ForConditionalGeneration.from_pretrained(model_path).to(device)
    model.eval()

    samples = _load_test_data(test_data_path)
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    smooth = SmoothingFunction().method1

    all_r1, all_r2, all_rL = [], [], []
    all_bleu1, all_bleu2, all_bleu3, all_bleu4 = [], [], [], []
    type_rougeL: dict[str, list[float]] = defaultdict(list)
    type_mastery_lengths: dict[str, list[int]] = defaultdict(list)

    for sample in samples:
        chunk = sample.get("chunk", "")
        topic = sample.get("topic", "")
        qtype = sample.get("question_type", "4a")
        mastery = sample.get("mastery_level", "Intermediate")
        score_cat = sample.get("score_category", "moderate")
        ref_q = sample.get("question", "")
        ref_a = sample.get("correct_answer", "")

        if not chunk or not ref_q:
            continue

        input_text = (
            f"generate question: type={qtype} topic={topic} "
            f"mastery={mastery} score_category={score_cat} context: {chunk}"
        )
        ref_text = f"question: {ref_q} | answer: {ref_a}"

        gen = _generate_text(model, tokenizer, input_text, device, max_new=128)

        # ROUGE
        scores = scorer.score(ref_text, gen)
        all_r1.append(scores["rouge1"].fmeasure)
        all_r2.append(scores["rouge2"].fmeasure)
        all_rL.append(scores["rougeL"].fmeasure)
        type_rougeL[qtype].append(scores["rougeL"].fmeasure)

        # BLEU
        ref_tokens = ref_text.split()
        gen_tokens = gen.split()
        if ref_tokens and gen_tokens:
            all_bleu1.append(sentence_bleu([ref_tokens], gen_tokens, weights=(1, 0, 0, 0), smoothing_function=smooth))
            all_bleu2.append(sentence_bleu([ref_tokens], gen_tokens, weights=(0.5, 0.5, 0, 0), smoothing_function=smooth))
            all_bleu3.append(sentence_bleu([ref_tokens], gen_tokens, weights=(0.33, 0.33, 0.33, 0), smoothing_function=smooth))
            all_bleu4.append(sentence_bleu([ref_tokens], gen_tokens, weights=(0.25, 0.25, 0.25, 0.25), smoothing_function=smooth))

        # Length tracking
        type_mastery_lengths[f"{qtype}_{mastery}"].append(len(gen_tokens))

    avg = lambda lst: round(np.mean(lst), 4) if lst else 0.0
    result = {
        "bleu1": avg(all_bleu1), "bleu2": avg(all_bleu2),
        "bleu3": avg(all_bleu3), "bleu4": avg(all_bleu4),
        "rouge1": avg(all_r1), "rouge2": avg(all_r2), "rougeL": avg(all_rL),
        "per_type_rougeL": {t: avg(v) for t, v in sorted(type_rougeL.items())},
        "avg_length_by_type_mastery": {k: round(np.mean(v), 1) for k, v in sorted(type_mastery_lengths.items())},
        "num_evaluated": len(all_rL),
    }
    logger.info("qg_evaluation_complete", **result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# DG EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_dg(model_path: str, test_data_path: str) -> dict:
    """Evaluate DG model: ROUGE-L, cosine sim per mastery, diversity."""
    from rouge_score import rouge_scorer

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = T5Tokenizer.from_pretrained(model_path)
    model = T5ForConditionalGeneration.from_pretrained(model_path).to(device)
    model.eval()
    embedder = _get_embedder()

    samples = _load_test_data(test_data_path)
    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)

    all_rougeL = []
    mastery_cosines: dict[str, list[float]] = defaultdict(list)
    diversity_scores: list[float] = []

    # Group samples by source question for diversity measurement
    question_distractors: dict[str, list[str]] = defaultdict(list)

    for sample in samples:
        question = sample.get("question", "")
        correct = sample.get("correct_answer", "")
        qtype = sample.get("question_type", "4a")
        mastery = sample.get("mastery_level", "Intermediate")
        score_cat = sample.get("score_category", "moderate")
        ref_distractors = sample.get("distractors", [])

        if not question or not correct or not ref_distractors:
            continue

        for ref_d in ref_distractors:
            input_text = (
                f"generate distractors: type={qtype} topic={sample.get('topic', '')} "
                f"mastery={mastery} score_category={score_cat} "
                f"question: {question} answer: {correct}"
            )

            gen = _generate_text(model, tokenizer, input_text, device, max_new=64)

            # ROUGE-L
            scores = scorer.score(ref_d, gen)
            all_rougeL.append(scores["rougeL"].fmeasure)

            # Cosine similarity to correct answer
            if gen.strip():
                embs = embedder.encode([correct, gen], convert_to_numpy=True, show_progress_bar=False)
                sim = cosine_similarity([embs[0]], [embs[1]])[0][0]
                mastery_cosines[mastery].append(float(sim))
                question_distractors[question].append(gen)

    # Diversity: % of semantically distinct distractors per question
    for q, dists in question_distractors.items():
        if len(dists) < 2:
            continue
        embs = embedder.encode(dists, convert_to_numpy=True, show_progress_bar=False)
        sims = cosine_similarity(embs)
        # Count pairs below 0.85 similarity as distinct
        n = len(dists)
        distinct_pairs = sum(1 for i in range(n) for j in range(i+1, n) if sims[i][j] < 0.85)
        total_pairs = n * (n - 1) / 2
        diversity_scores.append(distinct_pairs / total_pairs if total_pairs > 0 else 1.0)

    avg = lambda lst: round(np.mean(lst), 4) if lst else 0.0
    result = {
        "rougeL": avg(all_rougeL),
        "cosine_sim_per_mastery": {m: avg(v) for m, v in sorted(mastery_cosines.items())},
        "diversity_score": avg(diversity_scores),
        "num_evaluated": len(all_rougeL),
    }
    logger.info("dg_evaluation_complete", **result)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONALIZATION EXPERIMENTS
# ═══════════════════════════════════════════════════════════════════════════════

def run_experiments(qg_model_path: str, dg_model_path: str, test_data_path: str) -> dict:
    """Run all 4 personalization measurement experiments."""
    from scipy import stats as scipy_stats

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    qg_tok = T5Tokenizer.from_pretrained(qg_model_path)
    qg_mod = T5ForConditionalGeneration.from_pretrained(qg_model_path).to(device)
    qg_mod.eval()
    dg_tok = T5Tokenizer.from_pretrained(dg_model_path)
    dg_mod = T5ForConditionalGeneration.from_pretrained(dg_model_path).to(device)
    dg_mod.eval()
    embedder = _get_embedder()

    samples = _load_test_data(test_data_path)[:50]

    from mcq.question_types import TYPE_COGNITIVE_LEVEL, MASTERY_TYPE_ELIGIBILITY
    import random
    random.seed(42)

    results = {}

    # ── Experiment 1: Mastery Effect ────────────────────────────────
    mastery_levels_cog: dict[str, list[int]] = {"Novice": [], "Intermediate": [], "Expert": []}
    for mastery in ["Novice", "Intermediate", "Expert"]:
        for s in samples:
            eligible = MASTERY_TYPE_ELIGIBILITY.get(mastery, ["4a"])
            qtype = random.choice(eligible)
            input_text = (
                f"generate question: type={qtype} topic={s.get('topic', '')} "
                f"mastery={mastery} score_category=moderate context: {s.get('chunk', '')}"
            )
            gen = _generate_text(qg_mod, qg_tok, input_text, device)
            mastery_levels_cog[mastery].append(TYPE_COGNITIVE_LEVEL.get(qtype, 2))

    # Chi-square test
    observed = np.array([
        [mastery_levels_cog[m].count(l) for l in range(1, 5)]
        for m in ["Novice", "Intermediate", "Expert"]
    ])
    observed = observed[:, observed.sum(axis=0) > 0]  # remove zero columns
    chi2, p_value = scipy_stats.chi2_contingency(observed)[:2] if observed.shape[1] > 1 else (0, 1)

    results["experiment_1_mastery_effect"] = {
        "avg_cognitive_level": {m: round(np.mean(v), 2) for m, v in mastery_levels_cog.items()},
        "chi2": round(chi2, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
    }

    # ── Experiment 2: Score Category Effect ─────────────────────────
    cat_cog: dict[str, list[int]] = {}
    cat_ordinal = {"very_weak": 1, "weak": 2, "moderate": 3, "strong": 4}
    for cat in ["very_weak", "weak", "moderate", "strong"]:
        cat_cog[cat] = []
        eligible = MASTERY_TYPE_ELIGIBILITY.get("Intermediate", ["4a"])
        for s in samples[:30]:
            qtype = random.choice(eligible)
            input_text = (
                f"generate question: type={qtype} topic={s.get('topic', '')} "
                f"mastery=Intermediate score_category={cat} context: {s.get('chunk', '')}"
            )
            gen = _generate_text(qg_mod, qg_tok, input_text, device)
            cat_cog[cat].append(TYPE_COGNITIVE_LEVEL.get(qtype, 2))

    x_ord = [cat_ordinal[c] for c in cat_cog for _ in cat_cog[c]]
    y_cog = [v for c in cat_cog for v in cat_cog[c]]
    pearson_r = round(np.corrcoef(x_ord, y_cog)[0, 1], 4) if len(x_ord) > 2 else 0.0

    results["experiment_2_score_category_effect"] = {
        "avg_cognitive_level": {c: round(np.mean(v), 2) for c, v in cat_cog.items()},
        "pearson_r": pearson_r,
        "confirmed": abs(pearson_r) > 0.7,
    }

    # ── Experiment 3: Distractor Difficulty Scaling ──────────────────
    novice_sims, expert_sims = [], []
    for s in samples[:20]:
        correct = s.get("correct_answer", "")
        if not correct:
            continue
        for mastery, sim_list in [("Novice", novice_sims), ("Expert", expert_sims)]:
            input_text = (
                f"generate distractors: type=4a topic={s.get('topic', '')} "
                f"mastery={mastery} score_category=moderate "
                f"question: {s.get('question', '')} answer: {correct}"
            )
            gen = _generate_text(dg_mod, dg_tok, input_text, device, max_new=64)
            if gen.strip():
                embs = embedder.encode([correct, gen], convert_to_numpy=True, show_progress_bar=False)
                sim = cosine_similarity([embs[0]], [embs[1]])[0][0]
                sim_list.append(float(sim))

    delta = round(np.mean(expert_sims) - np.mean(novice_sims), 4) if novice_sims and expert_sims else 0.0
    t_stat, t_pval = scipy_stats.ttest_rel(expert_sims[:min(len(expert_sims), len(novice_sims))],
                                            novice_sims[:min(len(expert_sims), len(novice_sims))]) if novice_sims and expert_sims else (0, 1)

    results["experiment_3_distractor_scaling"] = {
        "novice_avg_sim": round(np.mean(novice_sims), 4) if novice_sims else 0,
        "expert_avg_sim": round(np.mean(expert_sims), 4) if expert_sims else 0,
        "delta": delta,
        "t_statistic": round(float(t_stat), 4),
        "p_value": round(float(t_pval), 4),
        "expert_harder": delta > 0,
    }

    # ── Experiment 4: Misconception Targeting ───────────────────────
    targeting_success = 0
    targeting_total = 0
    misconception_samples = [s for s in samples if s.get("misconception_context")][:30]

    for s in misconception_samples:
        correct = s.get("correct_answer", "")
        prev_wrong = s.get("misconception_context", "")
        if not correct or not prev_wrong:
            continue

        input_text = (
            f"generate distractors: type={s.get('question_type', '4b')} "
            f"topic={s.get('topic', '')} mastery={s.get('mastery_level', 'Intermediate')} "
            f"score_category={s.get('score_category', 'moderate')} "
            f"question: {s.get('question', '')} answer: {correct}"
        )
        gen = _generate_text(dg_mod, dg_tok, input_text, device, max_new=64)

        if gen.strip():
            embs = embedder.encode([prev_wrong, gen], convert_to_numpy=True, show_progress_bar=False)
            sim = cosine_similarity([embs[0]], [embs[1]])[0][0]
            targeting_total += 1
            if sim > 0.6:
                targeting_success += 1

    results["experiment_4_misconception_targeting"] = {
        "total_tested": targeting_total,
        "targeting_success": targeting_success,
        "success_rate": round(targeting_success / max(targeting_total, 1), 4),
    }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(qg_results: dict, dg_results: dict, experiment_results: dict, output_path: str):
    """Write JSON report and print formatted summary."""
    report = {
        "qg_metrics": qg_results,
        "dg_metrics": dg_results,
        "personalization_experiments": experiment_results,
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 60)
    print("MCQ EVALUATION REPORT")
    print("=" * 60)
    print("\n── QG Metrics ──")
    for k, v in qg_results.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")
    print("\n── DG Metrics ──")
    for k, v in dg_results.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")
    print("\n── Experiments ──")
    for name, data in experiment_results.items():
        print(f"\n  {name}:")
        for k, v in data.items():
            print(f"    {k}: {v}")
    print("\n" + "=" * 60)
    print(f"  Report saved to: {output_path}")
    print("=" * 60 + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Evaluate MCQ QG and DG models.")
    parser.add_argument("--qg-model", required=True, help="Path to fine-tuned QG model.")
    parser.add_argument("--dg-model", required=True, help="Path to fine-tuned DG model.")
    parser.add_argument("--test-data", required=True, help="Path to mcq_raw.jsonl test data.")
    parser.add_argument("--output", required=True, help="Output path for JSON report.")
    args = parser.parse_args()

    print("Evaluating QG model...")
    qg_results = evaluate_qg(args.qg_model, args.test_data)
    print("Evaluating DG model...")
    dg_results = evaluate_dg(args.dg_model, args.test_data)
    print("Running personalization experiments...")
    experiment_results = run_experiments(args.qg_model, args.dg_model, args.test_data)
    generate_report(qg_results, dg_results, experiment_results, args.output)


if __name__ == "__main__":
    main()
