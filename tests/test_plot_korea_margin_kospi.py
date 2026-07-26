from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import plot_korea_margin_kospi as module


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.status = 200
        self.headers = {"Content-Type": "application/json; charset=UTF-8"}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FetchJsonTests(unittest.TestCase):
    def test_retries_truncated_json_then_returns_valid_payload(self) -> None:
        request = Request("https://example.test/data")
        responses = [FakeResponse(b'{"ds1":['), FakeResponse(b'{"ds1":[]}')]

        with (
            patch.object(module, "urlopen", side_effect=responses),
            patch.object(module.random, "uniform", return_value=0.0),
            patch.object(module.time, "sleep") as sleep,
        ):
            payload = module.fetch_json(request)

        self.assertEqual(payload, {"ds1": []})
        sleep.assert_called_once_with(module.JSON_RETRY_DELAYS[0])


class KofiaFallbackTests(unittest.TestCase):
    def test_date_ranges_are_contiguous_and_bounded(self) -> None:
        ranges = module.kofia_date_ranges(date(2024, 1, 1), date(2025, 1, 1))

        self.assertEqual(ranges[0][0], date(2024, 1, 1))
        self.assertEqual(ranges[-1][1], date(2025, 1, 1))
        for index, (start_day, end_day) in enumerate(ranges):
            self.assertLessEqual((end_day - start_day).days + 1, module.KOFIA_CHUNK_DAYS)
            if index:
                self.assertEqual(start_day, ranges[index - 1][1] + timedelta(days=1))

    def test_full_range_failure_uses_segmented_requests(self) -> None:
        calls: list[tuple[date, date]] = []

        def fake_fetch(start_day: date, end_day: date) -> list[dict]:
            calls.append((start_day, end_day))
            if len(calls) == 1:
                raise RuntimeError("truncated response")
            return [
                {
                    "TMPV1": start_day.strftime("%Y%m%d"),
                    "TMPV2": "1000000",
                    "TMPV3": "600000",
                    "TMPV4": "400000",
                }
            ]

        with (
            patch.object(module, "fetch_kofia_rows", side_effect=fake_fetch),
            patch.object(module.time, "sleep"),
        ):
            frame = module.fetch_credit_financing_balance()

        self.assertGreater(len(calls), 2)
        self.assertFalse(frame.empty)
        for start_day, end_day in calls[1:]:
            self.assertLessEqual((end_day - start_day).days + 1, module.KOFIA_CHUNK_DAYS)


if __name__ == "__main__":
    unittest.main()
