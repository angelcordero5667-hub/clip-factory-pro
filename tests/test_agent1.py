import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent1_transcription.transcriber import AudioTranscriber

class TestAgent1Transcription(unittest.TestCase):

    def setUp(self):
        self.transcriber = AudioTranscriber(model_size="tiny", device="cpu", compute_type="int8", cpu_threads=4)

    def test_transcriber_initialization(self):
        self.assertEqual(self.transcriber.model_size, "tiny")
        self.assertEqual(self.transcriber.device, "cpu")
        self.assertEqual(self.transcriber.compute_type, "int8")
        self.assertIsNone(self.transcriber._model)

    def test_transcriber_default_model(self):
        t = AudioTranscriber()
        self.assertIn(t.model_size, ("large-v3-turbo", "small"))

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.transcriber.transcribe("non_existent_file_12345.mp4")

    @patch("faster_whisper.WhisperModel")
    def test_mock_transcription_pipeline(self, mock_whisper_class):
        mock_instance = MagicMock()
        mock_whisper_class.return_value = mock_instance

        # Mock segment and info
        mock_word = MagicMock()
        mock_word.word = "Hola"
        mock_word.start = 0.5
        mock_word.end = 0.8
        mock_word.probability = 0.98

        mock_seg = MagicMock()
        mock_seg.start = 0.5
        mock_seg.end = 2.0
        mock_seg.text = "Hola a todos"
        mock_seg.words = [mock_word]

        mock_info = MagicMock()
        mock_info.language = "es"
        mock_info.duration = 2.0
        mock_info.language_probability = 0.99

        mock_instance.transcribe.return_value = ([mock_seg], mock_info)

        # Create dummy file
        dummy_file = Path("tests/dummy_test_audio.wav")
        dummy_file.parent.mkdir(exist_ok=True)
        dummy_file.write_text("dummy")

        try:
            result = self.transcriber.transcribe(str(dummy_file))
            self.assertIsInstance(result, TranscriptResult)
            self.assertEqual(result.language, "es")
            self.assertEqual(len(result.segments), 1)
            self.assertEqual(result.segments[0].text, "Hola a todos")
            self.assertEqual(len(result.segments[0].words), 1)
            self.assertEqual(result.segments[0].words[0].word, "Hola")
        finally:
            if dummy_file.exists():
                dummy_file.unlink()

if __name__ == "__main__":
    unittest.main()
