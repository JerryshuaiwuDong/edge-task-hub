import unittest

from app.feishu.events import FeishuEventError, parse_feishu_event


class FeishuEventsTest(unittest.TestCase):
    def test_url_verification_challenge(self):
        parsed = parse_feishu_event(
            {"type": "url_verification", "token": "verify-token", "challenge": "abc123"},
            verification_token="verify-token",
        )

        self.assertEqual(parsed.kind, "challenge")
        self.assertEqual(parsed.challenge, "abc123")

    def test_text_message_event(self):
        parsed = parse_feishu_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt_1",
                    "event_type": "im.message.receive_v1",
                    "token": "verify-token",
                },
                "event": {
                    "sender": {"sender_id": {"open_id": "ou_1"}},
                    "message": {
                        "message_id": "om_1",
                        "chat_id": "oc_1",
                        "message_type": "text",
                        "content": "{\"text\":\"remind me tomorrow at 12:00 to eat lunch\"}",
                    },
                },
            },
            verification_token="verify-token",
        )

        self.assertEqual(parsed.kind, "message")
        self.assertEqual(parsed.event_id, "evt_1")
        self.assertEqual(parsed.message_id, "om_1")
        self.assertEqual(parsed.open_id, "ou_1")
        self.assertEqual(parsed.chat_id, "oc_1")
        self.assertEqual(parsed.message_type, "text")
        self.assertEqual(parsed.text, "remind me tomorrow at 12:00 to eat lunch")

    def test_rejects_token_mismatch(self):
        with self.assertRaises(FeishuEventError):
            parse_feishu_event(
                {"type": "url_verification", "token": "wrong", "challenge": "abc123"},
                verification_token="verify-token",
            )


if __name__ == "__main__":
    unittest.main()
