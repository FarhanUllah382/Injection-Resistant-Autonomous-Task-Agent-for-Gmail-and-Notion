"""
Evaluation Module

Compares Claude's extractions against human labels and measures accuracy.
"""

import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class EvaluationMetrics:
    """Results of evaluation."""
    total_emails: int
    actionable_correct: int  # correctly identified actionable emails
    actionable_incorrect: int  # incorrectly missed or added actionable
    not_actionable_correct: int  # correctly identified non-actionable
    not_actionable_incorrect: int  # incorrectly marked as actionable
    precision: float  # of emails marked actionable by Claude, % correct
    recall: float  # of truly actionable emails, % caught by Claude
    f1_score: float  # harmonic mean of precision and recall
    false_positives: int  # Claude said actionable, but it's not
    false_negatives: int  # Claude said not actionable, but it is
    avg_confidence: float
    high_confidence_accuracy: float  # accuracy for confidence >= 0.7
    confidence_distribution: Dict[str, int]  # buckets of confidence scores


def evaluate_extraction(predictions: List[Dict[str, Any]], labels: List[Dict[str, Any]]) -> Tuple[EvaluationMetrics, List[Dict[str, Any]]]:
    """
    Evaluate Claude's extractions against human labels.
    
    Args:
        predictions: list of Claude extraction results
        labels: list of human ground-truth labels
    
    Returns:
        (EvaluationMetrics, detailed_results_list)
    """
    
    if len(predictions) != len(labels):
        raise ValueError(f"Predictions and labels must have same length: {len(predictions)} vs {len(labels)}")
    
    total = len(predictions)
    actionable_correct = 0
    actionable_incorrect = 0
    not_actionable_correct = 0
    not_actionable_incorrect = 0
    false_positives = 0
    false_negatives = 0
    high_confidence_correct = 0
    high_confidence_total = 0
    confidence_buckets = {}
    confidences = []
    
    detailed_results = []
    
    for i, (pred, label) in enumerate(zip(predictions, labels)):
        pred_actionable = pred.get("actionable", False)
        true_actionable = label.get("actionable", False)
        confidence = pred.get("confidence", 0.0)
        confidences.append(confidence)
        
        # Bucket confidence
        bucket = f"{int(confidence * 10) * 10}%"
        confidence_buckets[bucket] = confidence_buckets.get(bucket, 0) + 1
        
        # Determine correctness
        is_correct = pred_actionable == true_actionable
        
        if true_actionable:
            if pred_actionable:
                actionable_correct += 1
            else:
                actionable_incorrect += 1
                false_negatives += 1
        else:
            if pred_actionable:
                not_actionable_incorrect += 1
                false_positives += 1
            else:
                not_actionable_correct += 1
        
        # Track high-confidence accuracy
        if confidence >= 0.7:
            high_confidence_total += 1
            if is_correct:
                high_confidence_correct += 1
        
        # Detailed result
        result_detail = {
            "email_id": i + 1,
            "pred_actionable": pred_actionable,
            "true_actionable": true_actionable,
            "correct": is_correct,
            "confidence": confidence,
            "task_match": pred.get("task") == label.get("task") if true_actionable else None,
            "deadline_match": pred.get("deadline") == label.get("deadline") if true_actionable else None,
            "assignee_match": pred.get("assignee") == label.get("assignee") if true_actionable else None,
            "pred_task": pred.get("task"),
            "true_task": label.get("task"),
            "pred_deadline": pred.get("deadline"),
            "true_deadline": label.get("deadline"),
            "pred_assignee": pred.get("assignee"),
            "true_assignee": label.get("assignee"),
            "pred_reason": pred.get("reason"),
            "true_reason": label.get("reason"),
        }
        detailed_results.append(result_detail)
    
    # Calculate metrics
    true_positives = actionable_correct
    true_negatives = not_actionable_correct
    
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    high_confidence_accuracy = high_confidence_correct / high_confidence_total if high_confidence_total > 0 else 0.0
    
    metrics = EvaluationMetrics(
        total_emails=total,
        actionable_correct=actionable_correct,
        actionable_incorrect=actionable_incorrect,
        not_actionable_correct=not_actionable_correct,
        not_actionable_incorrect=not_actionable_incorrect,
        precision=precision,
        recall=recall,
        f1_score=f1,
        false_positives=false_positives,
        false_negatives=false_negatives,
        avg_confidence=avg_confidence,
        high_confidence_accuracy=high_confidence_accuracy,
        confidence_distribution=confidence_buckets,
    )
    
    return metrics, detailed_results


def print_metrics(metrics: EvaluationMetrics) -> None:
    """Pretty-print evaluation metrics."""
    print("\n" + "=" * 70)
    print("EXTRACTION EVALUATION RESULTS")
    print("=" * 70)
    
    print(f"\nTotal emails evaluated: {metrics.total_emails}")
    
    print(f"\nACTIONABILITY CLASSIFICATION:")
    print(f"  Actionable (correct):     {metrics.actionable_correct}")
    print(f"  Actionable (incorrect):   {metrics.actionable_incorrect}")
    print(f"  Non-actionable (correct): {metrics.not_actionable_correct}")
    print(f"  Non-actionable (incorrect): {metrics.not_actionable_incorrect}")
    
    print(f"\nFALSE POSITIVES / FALSE NEGATIVES:")
    print(f"  False positives (said actionable, not): {metrics.false_positives}")
    print(f"  False negatives (missed actionable):    {metrics.false_negatives}")
    
    print(f"\nKEY METRICS:")
    print(f"  Precision: {metrics.precision:.1%} (of actionable predictions, how many correct)")
    print(f"  Recall:    {metrics.recall:.1%} (of truly actionable, how many caught)")
    print(f"  F1 Score:  {metrics.f1_score:.3f}")
    
    print(f"\nCONFIDENCE:")
    print(f"  Average confidence: {metrics.avg_confidence:.2f}")
    print(f"  Accuracy for confidence >= 0.7: {metrics.high_confidence_accuracy:.1%}")
    print(f"  Confidence distribution: {metrics.confidence_distribution}")
    
    print("\n" + "=" * 70)
