from __future__ import annotations

from audit_pre_action_observability import classify_order_fields


def test_order_field_classes_keep_post_fill_fields_out_of_submission_class() -> None:
    classes = classify_order_fields(["timestamp", "side", "orderQty", "price", "avgPx", "cumQty", "ordStatus"])
    assert "side" in classes["contemporaneous_submission"]
    assert "orderQty" in classes["contemporaneous_submission"]
    assert "avgPx" in classes["post_fill_sensitive"]
    assert "cumQty" in classes["post_fill_sensitive"]
    assert "avgPx" not in classes["contemporaneous_submission"]


def test_unknown_fields_are_reported_without_being_called_pre_action() -> None:
    classes = classify_order_fields(["timestamp", "customPrivateField"])
    assert classes["other"] == ["customPrivateField"]
