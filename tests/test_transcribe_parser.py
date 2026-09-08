import unittest

from app.aws_transcribe import clean_extension, make_srt, parse_transcribe_json


class TranscribeParserTests(unittest.TestCase):
    def test_groups_items_into_segments(self):
        payload = {
            "results": {
                "transcripts": [{"transcript": "Hola mundo. Segunda frase."}],
                "items": [
                    {
                        "type": "pronunciation",
                        "start_time": "0.10",
                        "end_time": "0.40",
                        "alternatives": [{"content": "Hola"}],
                    },
                    {
                        "type": "pronunciation",
                        "start_time": "0.45",
                        "end_time": "0.90",
                        "alternatives": [{"content": "mundo"}],
                    },
                    {"type": "punctuation", "alternatives": [{"content": "."}]},
                    {
                        "type": "pronunciation",
                        "start_time": "1.20",
                        "end_time": "1.80",
                        "alternatives": [{"content": "Segunda"}],
                    },
                    {
                        "type": "pronunciation",
                        "start_time": "1.90",
                        "end_time": "2.40",
                        "alternatives": [{"content": "frase"}],
                    },
                    {"type": "punctuation", "alternatives": [{"content": "."}]},
                ],
            }
        }
        result = parse_transcribe_json(payload)
        self.assertEqual(result.text, "Hola mundo. Segunda frase.")
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[0]["text"], "Hola mundo.")
        self.assertEqual(result.segments[0]["start"], 0.1)

    def test_prefers_audio_segments_when_available(self):
        payload = {
            "results": {
                "audio_segments": [
                    {"start_time": "3.0", "end_time": "5.5", "transcript": "Texto listo"}
                ]
            }
        }
        result = parse_transcribe_json(payload)
        self.assertEqual(result.text, "Texto listo")
        self.assertEqual(result.segments[0]["end"], 5.5)

    def test_srt_format(self):
        srt = make_srt([{"start": 1.2, "end": 3.4, "text": "Hola"}])
        self.assertIn("00:00:01,200 --> 00:00:03,400", srt)

    def test_rejects_unsupported_format(self):
        with self.assertRaises(ValueError):
            clean_extension("video.mov")


if __name__ == "__main__":
    unittest.main()

