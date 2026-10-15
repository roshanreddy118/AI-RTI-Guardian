"""Checks for the rule-based anomaly detector. No network, no framework.

Run: python3 test_anomalies.py
Each case asserts a specific finding fires (or stays silent) on crafted text, so a
regression that drops or fabricates a finding fails loudly.
"""
import anomalies


def has(findings, needle):
    return any(needle.lower() in f["finding"].lower() for f in findings)


def test_repeated_vendor():
    text = ("Contract 1 awarded to Sunrise Constructions Pvt Ltd. "
            "Contract 2 awarded to Sunrise Constructions Pvt Ltd. "
            "Contract 3 awarded to Sunrise Constructions Pvt Ltd.")
    f = anomalies.detect(text)
    assert has(f, "same vendor"), f
    print("ok: repeated vendor detected")


def test_repeated_vendor_reported_once():
    # Regression: the suffix alternation used to split "Sunrise Constructions Pvt Ltd"
    # into two tokens, firing the finding twice and swallowing leading words.
    text = ("Contract to Sunrise Constructions Pvt Ltd. "
            "Contract to Sunrise Constructions Pvt Ltd. "
            "Contract to Sunrise Constructions Pvt Ltd.")
    f = [x for x in anomalies.detect(text) if "same vendor" in x["finding"].lower()]
    assert len(f) == 1, f
    assert "sunrise constructions pvt ltd" in f[0]["evidence"].lower(), f
    print("ok: repeated vendor reported exactly once")


def test_vendor_below_threshold_silent():
    text = "Contract 1 to Sunrise Constructions Pvt Ltd. Contract 2 to Moon Traders."
    f = anomalies.detect(text)
    assert not has(f, "same vendor"), f
    print("ok: two different vendors do not trip the rule")


def test_shared_address():
    text = ("Bidder A, Plot 12 MG Road, 560001. "
            "Bidder B, Plot 12 MG Road, 560001.")
    f = anomalies.detect(text)
    assert has(f, "address"), f
    print("ok: shared address detected")


def test_amount_jump():
    text = "Awarded amount: Rs 50 lakh. Final payment: Rs 1.7 crore."
    f = anomalies.detect(text)
    assert has(f, "increased"), f
    print("ok: amount escalation detected")


def test_payment_before_cc():
    text = "Payment of Rs 10 lakh was released. The completion certificate was issued later."
    f = anomalies.detect(text)
    assert has(f, "payment appears before completion"), f
    print("ok: payment-before-CC detected")


def test_missing_pages():
    text = "The matter is covered in pages 41 to 53 of the file."
    f = anomalies.detect(text)
    assert has(f, "pages 41-53"), f
    print("ok: referenced-but-missing pages detected")


def test_pages_present_when_enclosed():
    text = "Pages 41 to 53 are enclosed herewith as Annexure A."
    f = anomalies.detect(text)
    assert not has(f, "pages 41-53"), f
    print("ok: enclosed pages do not trip the rule")


def test_exemption_recommends_appeal():
    text = "The information is exempt under Section 8(1)(d) and cannot be provided."
    f = anomalies.detect(text)
    assert has(f, "exemption"), f
    assert anomalies.recommend(f) == "first_appeal", f
    print("ok: wrongful exemption -> first appeal")


def test_clean_response_silent():
    text = "Please find enclosed the certified copies of all requested records. Nothing withheld."
    f = anomalies.detect(text)
    assert f == [], f
    assert anomalies.recommend(f) == "none"
    print("ok: clean response yields no findings")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("\nAll anomaly checks passed.")
