"""Transcription worker: chunk audio timeline and merge overlapping segments."""
from dataclasses import dataclass
from typing import Any, Generator

from app.workers.base import BaseJobHandler


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Immutable segment of transcribed audio."""
    start: float
    end: float
    text: str


class TranscriptionHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Produces timestamped transcript segments (simulated until real audio ingest)."""

    def __init__(self, chunk_duration: float = 30.0, overlap: float = 2.0):
        self._chunk_duration = chunk_duration
        self._overlap = overlap

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        file_path = input_payload.get("file_path")
        audio_url = input_payload.get("audio_url")
        text_for_alignment = input_payload.get("text")

        if file_path is None and audio_url is None and text_for_alignment is None:
            raise ValueError(
                "Transcription requires 'file_path', 'audio_url', "
                "or 'text' (for simulated transcription)"
            )

        duration = input_payload.get("duration")
        if duration is not None:
            if not isinstance(duration, (int, float)) or duration <= 0:
                raise ValueError("'duration' must be a positive number (seconds)")
            if duration > 7200:
                raise ValueError("Maximum audio duration is 2 hours (7200 seconds)")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Chunk the timeline, transcribe, merge overlaps, and align timestamps."""
        duration = input_payload.get("duration", 60.0)
        text = input_payload.get("text", "")

        chunks = list(self._generate_time_chunks(duration))

        raw_segments = self._transcribe_chunks(chunks, text)

        merged_segments = self._merge_overlapping_segments(raw_segments)

        aligned_segments = self._align_timestamps(merged_segments)

        return {
            "segments": [
                {"start": seg.start, "end": seg.end, "text": seg.text}
                for seg in aligned_segments
            ],
            "duration": duration,
            "chunk_count": len(chunks),
            "segment_count": len(aligned_segments),
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        full_transcript = " ".join(
            seg["text"] for seg in raw_result["segments"]
        )
        return {
            "transcript": full_transcript,
            "segments": raw_result["segments"],
            "duration": raw_result["duration"],
            "chunk_count": raw_result["chunk_count"],
            "segment_count": raw_result["segment_count"],
        }

    def _generate_time_chunks(
        self, total_duration: float
    ) -> Generator[tuple[float, float], None, None]:
        """Yield overlapping (start, end) windows across the audio duration."""
        step = self._chunk_duration - self._overlap
        start = 0.0

        while start < total_duration:
            end = min(start + self._chunk_duration, total_duration)
            yield (round(start, 2), round(end, 2))
            if end >= total_duration:
                break
            start += step

    def _transcribe_chunks(
        self,
        chunks: list[tuple[float, float]],
        source_text: str,
    ) -> list[TranscriptSegment]:
        """Distribute source text across time chunks (placeholder for Whisper)."""
        if not source_text:
            source_text = (
                "This is a simulated transcription output. "
                "Each chunk represents a segment of the audio file. "
                "Real transcription will use OpenAI Whisper model."
            )

        words = source_text.split()
        total_words = len(words)
        words_per_chunk = max(1, total_words // len(chunks)) if chunks else 0

        segments = []
        word_idx = 0

        for start, end in chunks:
            chunk_end_idx = min(word_idx + words_per_chunk, total_words)
            chunk_words = words[word_idx:chunk_end_idx]
            chunk_text = " ".join(chunk_words) if chunk_words else "[silence]"

            segments.append(TranscriptSegment(start=start, end=end, text=chunk_text))
            word_idx = chunk_end_idx

        if word_idx < total_words and segments:
            last = segments[-1]
            remaining = " ".join(words[word_idx:])
            segments[-1] = TranscriptSegment(
                start=last.start,
                end=last.end,
                text=f"{last.text} {remaining}",
            )

        return segments

    def _merge_overlapping_segments(
        self, segments: list[TranscriptSegment]
    ) -> list[TranscriptSegment]:
        """Merge overlapping transcript segments into a non-overlapping list."""
        if not segments:
            return []

        sorted_segments = sorted(segments, key=lambda s: s.start)

        merged: list[TranscriptSegment] = [sorted_segments[0]]

        for current in sorted_segments[1:]:
            previous = merged[-1]

            if current.start <= previous.end:
                merged_text = self._merge_texts(previous.text, current.text)
                merged[-1] = TranscriptSegment(
                    start=previous.start,
                    end=max(previous.end, current.end),
                    text=merged_text,
                )
            else:
                merged.append(current)

        return merged

    def _align_timestamps(
        self, segments: list[TranscriptSegment]
    ) -> list[TranscriptSegment]:
        """Snap segment boundaries so each start equals the previous end."""
        if len(segments) <= 1:
            return segments

        aligned = [segments[0]]

        for i in range(1, len(segments)):
            current = segments[i]
            prev_end = aligned[-1].end
            aligned.append(TranscriptSegment(
                start=prev_end,
                end=max(current.end, prev_end + 0.01),
                text=current.text,
            ))

        return aligned

    @staticmethod
    def _merge_texts(text_a: str, text_b: str) -> str:
        """Merge overlapping chunk text without duplicating shared words."""
        words_a = text_a.split()
        words_b = text_b.split()

        max_overlap = min(len(words_a), len(words_b))

        for overlap_size in range(max_overlap, 0, -1):
            if words_a[-overlap_size:] == words_b[:overlap_size]:
                combined = words_a + words_b[overlap_size:]
                return " ".join(combined)

        return f"{text_a} {text_b}"
