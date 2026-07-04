"""
Transcription Worker — Stage 6.

DSA Focus:
----------
- Audio Chunking: split audio into fixed-duration segments
- Merge Intervals: combine overlapping transcript segments
- Timestamp Alignment: ensure continuous, non-overlapping timeline

Python Internals Focus:
-----------------------
- Named tuples / dataclasses for structured intermediate data
- Sorting with key functions (DSA: comparison-based sort O(n log n))
- Generator for streaming chunks of audio
"""
from dataclasses import dataclass
from typing import Any, Generator

from app.workers.base import BaseJobHandler


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """
    Immutable segment of transcribed audio.

    frozen=True: makes it hashable and prevents accidental mutation.
    slots=True: uses __slots__ instead of __dict__ — less memory per instance.
    """
    start: float
    end: float
    text: str


class TranscriptionHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """
    Transcribes audio input into timestamped text segments.

    Currently simulates transcription (real Whisper integration in Stage 9
    when file uploads are added). The DSA logic (chunking, merging) is real.
    """

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
        """
        DSA: Audio Chunking + Merge Intervals.

        1. Chunk the audio into overlapping time windows
        2. "Transcribe" each chunk (simulated for now)
        3. Merge overlapping segments to remove duplicates
        4. Align timestamps for continuous output

        Merge Intervals algorithm:
        - Sort segments by start time: O(n log n)
        - Single pass to merge overlapping ones: O(n)
        - Total: O(n log n)
        """
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
        """
        DSA: Sliding window over time axis.

        Generates (start, end) tuples for each audio chunk.
        Overlap ensures no words are cut at boundaries.

        Same sliding window concept as text chunking in summarization,
        but applied to time instead of word count.
        """
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
        """
        Simulate transcription by distributing source text across chunks.
        In Stage 9, this will call Whisper on actual audio bytes.
        """
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
        """
        DSA: Merge Intervals — Classic algorithm.

        Given a list of intervals that may overlap, merge them into
        non-overlapping intervals.

        Algorithm:
        1. Sort by start time → O(n log n)
        2. Iterate: if current overlaps with previous, merge them → O(n)

        Total: O(n log n) dominated by the sort.

        Why this matters for transcription:
        - Overlapping audio chunks produce overlapping text segments
        - We must merge them so the final transcript isn't duplicated
        """
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
        """
        DSA: Timestamp Alignment.

        Ensure segments form a continuous, non-overlapping timeline.
        Each segment's start == previous segment's end.

        This is a simple O(n) pass that "snaps" boundaries together.
        """
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
        """
        Simple text deduplication for overlapping segments.
        Finds the longest suffix of text_a that is a prefix of text_b,
        then merges without duplication.

        DSA: String matching — O(min(len_a, len_b)) in worst case.
        """
        words_a = text_a.split()
        words_b = text_b.split()

        max_overlap = min(len(words_a), len(words_b))

        for overlap_size in range(max_overlap, 0, -1):
            if words_a[-overlap_size:] == words_b[:overlap_size]:
                combined = words_a + words_b[overlap_size:]
                return " ".join(combined)

        return f"{text_a} {text_b}"