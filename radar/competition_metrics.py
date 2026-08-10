from __future__ import annotations

import statistics
from collections import Counter
from typing import Iterable

from radar.config import RadarConfig
from radar.models import CompetitionMetrics, HistoricalAnalog


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def med(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def confidence_for_sample(size: int, config: RadarConfig) -> str:
    if size >= config.historical.dumping.minimum_sample_for_high_confidence:
        return "HIGH"
    if size >= config.historical.dumping.minimum_sample_for_medium_confidence:
        return "MEDIUM"
    if size >= 2:
        return "LOW"
    return "INSUFFICIENT"


def calculate_competition_metrics(analogs: list[HistoricalAnalog], config: RadarConfig) -> CompetitionMetrics:
    complete = [a for a in analogs if a.result_data_status == "COMPLETE"]
    partial = [a for a in analogs if a.result_data_status == "PARTIAL"]
    participants = [float(a.participant_count) for a in analogs if a.participant_count is not None]
    reductions = [float(a.reduction_percent) for a in analogs if a.reduction_percent is not None]
    winners = [a.winner_name for a in analogs if a.winner_name]
    repeated = sum(count for _winner, count in Counter(winners).items() if count > 1)
    total = len(analogs)
    strong = [a for a in analogs if a.similarity_score >= config.historical.similarity.strong_similarity_score]
    participant_contributors = [a.analog_procurement_number for a in analogs if a.participant_count is not None]
    reduction_contributors = [a.analog_procurement_number for a in analogs if a.reduction_percent is not None]
    winner_contributors = [a.analog_procurement_number for a in analogs if a.winner_name]
    no_application_contributors = [a.analog_procurement_number for a in analogs if a.no_applications]
    complete_contributors = [a.analog_procurement_number for a in complete]
    participant_confidence = confidence_for_sample(len(participant_contributors), config)
    reduction_confidence = confidence_for_sample(len(reduction_contributors), config)
    winner_confidence = confidence_for_sample(len(winner_contributors), config)
    confidence_rank = {"INSUFFICIENT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
    confidence = max((participant_confidence, reduction_confidence, winner_confidence), key=lambda item: confidence_rank[item], default="INSUFFICIENT")
    return CompetitionMetrics(
        analog_count_total=total,
        analog_count_with_complete_results=len(complete),
        analog_count_partial=len(partial),
        participant_sample_size=len(participant_contributors),
        reduction_sample_size=len(reduction_contributors),
        winner_sample_size=len(winner_contributors),
        complete_result_sample_size=len(complete_contributors),
        no_application_sample_size=len(no_application_contributors),
        strong_analog_count=len(strong),
        median_participants=med(participants),
        average_participants=avg(participants),
        participants_p25=percentile(participants, 0.25),
        participants_p75=percentile(participants, 0.75),
        maximum_participants=int(max(participants)) if participants else None,
        median_reduction_percent=med(reductions),
        average_reduction_percent=avg(reductions),
        reduction_p25=percentile(reductions, 0.25),
        reduction_p75=percentile(reductions, 0.75),
        maximum_reduction_percent=max(reductions) if reductions else None,
        high_reduction_rate=round(sum(1 for value in reductions if value >= config.historical.dumping.high_reduction_threshold) / len(reductions), 3) if reductions else 0,
        extreme_reduction_count=sum(1 for value in reductions if value >= config.historical.dumping.extreme_reduction_threshold),
        extreme_reduction_rate=round(sum(1 for value in reductions if value >= config.historical.dumping.extreme_reduction_threshold) / len(reductions), 3) if reductions else 0,
        severe_reduction_rate=round(sum(1 for value in reductions if value >= config.historical.dumping.severe_reduction_threshold) / len(reductions), 3) if reductions else 0,
        no_application_count=sum(1 for a in analogs if a.no_applications),
        no_application_rate=round(sum(1 for a in analogs if a.no_applications) / total, 3) if total else 0,
        all_rejected_count=sum(1 for a in analogs if a.all_applications_rejected),
        all_rejected_rate=round(sum(1 for a in analogs if a.all_applications_rejected) / total, 3) if total else 0,
        cancelled_count=sum(1 for a in analogs if a.result_data_status == "CANCELLED"),
        cancellation_rate=round(sum(1 for a in analogs if a.result_data_status == "CANCELLED") / total, 3) if total else 0,
        repeated_winner_count=repeated,
        repeated_winner_share=round(repeated / len(winners), 3) if winners else 0,
        sample_quality=confidence,
        confidence=confidence,
        participant_metric_confidence=participant_confidence,
        reduction_metric_confidence=reduction_confidence,
        winner_metric_confidence=winner_confidence,
        participant_contributors=participant_contributors,
        reduction_contributors=reduction_contributors,
        winner_contributors=winner_contributors,
        no_application_contributors=no_application_contributors,
        complete_result_contributors=complete_contributors,
        warnings=[] if max(len(participant_contributors), len(reduction_contributors), len(winner_contributors), len(complete_contributors), 0) >= 2 else ["insufficient analog sample"],
    )
