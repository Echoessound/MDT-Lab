from mdt_demo.research.adjudication import compute_agreement_report


READY = "READY_FOR_REVIEW"
NEED = "NEED_MORE_INFORMATION"


def agreement(scenarios):
    submissions = {
        str(i): {
            name: {
                "annotator_id": name, "expected_decision": decision,
                "required_agents": ["oncology", "surgery"] if decision == READY else ["oncology"],
                "case_id": str(i), "case_version": 1, "trigger_event_id": "E1",
            }
            for name, decision in ratings.items()
        }
        for i, ratings in enumerate(scenarios)
    }
    return compute_agreement_report(submissions, {})


def test_two_rater_kappa_uses_separate_marginals_and_counts_each_cutoff_once():
    ratings = [
        {"b": READY, "a": READY}, {"a": READY, "b": NEED},
        {"a": READY, "b": NEED}, {"a": NEED, "b": NEED},
    ]
    report = agreement(ratings)
    stats = report["decision_agreement"]
    assert stats["pair_count"] == 4
    assert stats["raw_agreement"] == 0.5
    # p_e = (3*1 + 1*3) / 4**2. κ = (0.5 - 0.375) / (1 - 0.375).
    assert stats["expected_agreement"] == 0.375
    assert stats["cohens_kappa"] == 0.2
    matrix = stats["confusion_matrix"]
    assert sum(sum(row.values()) for row in matrix.values()) == 4
    assert (matrix[READY][NEED], matrix[NEED][READY]) == (2, 0)
    assert report["specialist_agreement"]["per_role"]["surgery"]["cohens_kappa"] == 0.2
    assert report["specialist_agreement"]["per_role"]["oncology"]["cohens_kappa"] is None
    pair = report["rater_pair_agreement"][0]
    assert pair["annotators"] == ["a", "b"]
    assert pair["decision_agreement"] == stats


def test_rotating_raters_report_kappa_only_on_items_shared_by_a_fixed_pair():
    report = agreement([
        {"c": NEED, "a": READY, "b": READY},
        {"a": NEED, "b": NEED},
        {"c": READY},
    ])
    pooled = report["decision_agreement"]
    assert pooled["pair_count"] == 4
    assert pooled["raw_agreement"] == 0.5
    assert pooled["expected_agreement"] is pooled["cohens_kappa"] is None
    assert report["specialist_agreement"]["per_role"]["surgery"]["cohens_kappa"] is None
    pairs = {tuple(item["annotators"]): item["decision_agreement"]
             for item in report["rater_pair_agreement"]}
    assert set(pairs) == {("a", "b"), ("a", "c"), ("b", "c")}
    assert (pairs["a", "b"]["pair_count"], pairs["a", "b"]["cohens_kappa"]) == (2, 1.0)
    assert (pairs["a", "c"]["pair_count"], pairs["a", "c"]["cohens_kappa"]) == (1, 0.0)
    assert agreement([{"a": NEED}])["rater_pair_agreement"] == []
