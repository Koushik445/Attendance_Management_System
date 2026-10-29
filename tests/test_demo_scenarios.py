"""
Automated test script for the demo scenarios described in the project spec.

This exercises fusion/decision_engine.py DIRECTLY with hand-built evidence
dictionaries - it does NOT need a running server, database, or dataset, so
it can be run immediately to validate the fusion policy logic itself.

For an end-to-end test against the real API/DB/dataset, see
tests/test_api_integration.py (requires the backend running + demo data
seeded).

Run:
    python tests/test_demo_scenarios.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fusion.decision_engine import decide  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"

# person ids used purely as symbolic stand-ins in these evidence fixtures
PERSON_A = 1
PERSON_B = 2


def face(person_id, similarity):
    return {"person_id": person_id, "similarity": similarity, "confidence": similarity} if person_id else None


def plate(person_id, confidence, plate_number="XX00XX0000"):
    return {"person_id": person_id, "plate_number": plate_number, "confidence": confidence} if person_id is not None or confidence else None


def id_card(person_id, confidence=0.99):
    return {"person_id": person_id, "confidence": confidence}


SCENARIOS = [
    {
        "name": "1. WALKING + GOOD FACE -> VERIFIED, face only",
        "evidence": {"arrival_type": "WALKING", "face": face(PERSON_A, 0.80), "plate": None, "id_card": None},
        "expect_decision": "VERIFIED",
        "expect_method": "FACE",
    },
    {
        "name": "2. WALKING + POOR FACE + CORRECT ID -> VERIFIED, face+ID",
        "evidence": {"arrival_type": "WALKING", "face": face(PERSON_A, 0.40), "plate": None, "id_card": id_card(PERSON_A)},
        "expect_decision": "VERIFIED",
        "expect_method": "FACE+ID",
    },
    {
        "name": "3. CAR + GOOD FACE + CORRECT PLATE -> VERIFIED, face+plate",
        "evidence": {"arrival_type": "CAR", "face": face(PERSON_A, 0.80), "plate": plate(PERSON_A, 0.92), "id_card": None},
        "expect_decision": "VERIFIED",
        "expect_method": "FACE+PLATE",
    },
    {
        "name": "4. CAR + LOW FACE + CORRECT PLATE -> NEEDS_ID (insufficient combined confidence)",
        "evidence": {"arrival_type": "CAR", "face": face(PERSON_A, 0.20), "plate": plate(PERSON_A, 0.92), "id_card": None},
        "expect_decision": "NEEDS_ID",
        "expect_method": "FACE+PLATE",
    },
    {
        "name": "5. CAR + CONFLICTING FACE/PLATE -> NEEDS_ID (conflict, ID requested)",
        "evidence": {"arrival_type": "CAR", "face": face(PERSON_A, 0.80), "plate": plate(PERSON_B, 0.90), "id_card": None},
        "expect_decision": "NEEDS_ID",
        "expect_method": "FACE+PLATE",
    },
    {
        "name": "6. BIKE + FACE + PLATE (both HIGH) -> VERIFIED",
        "evidence": {"arrival_type": "BIKE", "face": face(PERSON_A, 0.85), "plate": plate(PERSON_A, 0.90), "id_card": None},
        "expect_decision": "VERIFIED",
        "expect_method": "FACE+PLATE",
    },
    {
        "name": "7. BIKE + LOW CONFIDENCE -> NEEDS_ID",
        "evidence": {"arrival_type": "BIKE", "face": face(PERSON_A, 0.30), "plate": plate(PERSON_A, 0.40), "id_card": None},
        "expect_decision": "NEEDS_ID",
        "expect_method": "FACE+PLATE",
    },
    {
        "name": "8. UNKNOWN PERSON (walking, no face match, no ID) -> UNKNOWN/NEEDS_ID (never auto-verified)",
        "evidence": {"arrival_type": "WALKING", "face": face(None, 0.0), "plate": None, "id_card": None},
        "expect_decision": "NEEDS_ID",
        "expect_method": "FACE",
    },
    {
        "name": "9. UNKNOWN PLATE (car, plate unregistered) -> falls back to ID when provided",
        "evidence": {"arrival_type": "CAR", "face": face(PERSON_A, 0.80), "plate": plate(None, 0.90), "id_card": id_card(PERSON_A)},
        "expect_decision": "VERIFIED",
        "expect_method": "FACE+PLATE+ID",
    },
    {
        "name": "10. ALL THREE CONFLICT -> MANUAL_REVIEW (never auto-verified)",
        "evidence": {
            "arrival_type": "CAR",
            "face": face(PERSON_A, 0.80),
            "plate": plate(PERSON_B, 0.90),
            "id_card": id_card(2001),  # a third, different identity
        },
        "expect_decision": "MANUAL_REVIEW",
        "expect_method": "FACE+PLATE+ID",
    },
]


def run():
    results = []
    for scenario in SCENARIOS:
        result = decide(scenario["evidence"])
        ok = (result["decision"] == scenario["expect_decision"]
              and result["verification_method"] == scenario["expect_method"])
        results.append((scenario, result, ok))

    print(f"{'Result':6} | {'Scenario':70} | {'Decision':14} | {'Method':14} | Reason")
    print("-" * 160)
    for scenario, result, ok in results:
        print(f"{PASS if ok else FAIL:6} | {scenario['name']:70} | {result['decision']:14} | "
              f"{result['verification_method']:14} | {result['reason']}")

    passed = sum(1 for *_, ok in results if ok)
    total = len(results)
    print("-" * 160)
    print(f"\n{passed}/{total} scenarios matched expected decision + verification method.")

    # Never-auto-verify-on-conflict invariant, checked explicitly across every scenario:
    for scenario, result, _ in results:
        if "CONFLICT" in scenario["name"].upper():
            assert result["decision"] != "VERIFIED", f"SAFETY VIOLATION: conflicting evidence was auto-verified in: {scenario['name']}"

    return passed == total


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
