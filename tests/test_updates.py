import json
import unittest

from publisher.updates import UpdateCheckError, UpdateStatus, check_for_update


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        return None


class _BytesResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        return None


class UpdateCheckTests(unittest.TestCase):
    def test_reports_a_newer_stable_github_release(self):
        report = check_for_update(
            "0.3.0",
            opener=lambda _request, timeout: _Response(
                {
                    "tag_name": "v0.4.0",
                    "html_url": "https://github.com/example/releases/tag/v0.4.0",
                    "name": "v0.4.0",
                }
            ),
        )

        self.assertEqual(report.status, UpdateStatus.AVAILABLE)
        self.assertEqual(report.latest_version, "0.4.0")
        self.assertEqual(
            report.release_url,
            "https://github.com/example/releases/tag/v0.4.0",
        )

    def test_reports_current_when_the_release_is_not_newer(self):
        report = check_for_update(
            "0.4.0",
            opener=lambda _request, timeout: _Response(
                {
                    "tag_name": "v0.3.9",
                    "html_url": "https://github.com/example/releases/tag/v0.3.9",
                }
            ),
        )

        self.assertEqual(report.status, UpdateStatus.CURRENT)
        self.assertEqual(report.latest_version, "0.3.9")

    def test_rejects_an_invalid_release_payload(self):
        with self.assertRaisesRegex(UpdateCheckError, "版本号"):
            check_for_update(
                "0.4.0",
                opener=lambda _request, timeout: _Response({"tag_name": "latest"}),
            )

    def test_uses_the_public_release_feed_when_the_api_is_rate_limited(self):
        feed = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>v0.4.0 发行说明</title>
    <link rel="alternate" href="https://github.com/example/releases/tag/v0.4.0" />
  </entry>
</feed>'''.encode("utf-8")

        def opener(request, timeout):
            if "api.github.com" in request.full_url:
                raise OSError("rate limited")
            return _BytesResponse(feed)

        report = check_for_update("0.3.0", opener=opener)

        self.assertEqual(report.status, UpdateStatus.AVAILABLE)
        self.assertEqual(report.latest_version, "0.4.0")
        self.assertEqual(
            report.release_url,
            "https://github.com/example/releases/tag/v0.4.0",
        )
