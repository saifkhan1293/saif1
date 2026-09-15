import pytest

from saif1.config import SessionRequest


def test_session_request_with_event_only():
    request = SessionRequest(year=2024, event="Bahrain Grand Prix")
    assert request.event == "Bahrain Grand Prix"
    assert request.round_number is None


def test_session_request_with_round_number_only():
    request = SessionRequest(year=2024, round_number=1)
    assert request.round_number == 1
    assert request.event is None


def test_session_request_rejects_both_event_and_round_number():
    with pytest.raises(ValueError, match="exactly one"):
        SessionRequest(year=2024, event="Bahrain Grand Prix", round_number=1)


def test_session_request_rejects_neither_event_nor_round_number():
    with pytest.raises(ValueError, match="exactly one"):
        SessionRequest(year=2024)


def test_session_request_invalid_session_type_still_rejected():
    with pytest.raises(ValueError, match="Unknown session_type"):
        SessionRequest(year=2024, round_number=1, session_type="ZZ")
