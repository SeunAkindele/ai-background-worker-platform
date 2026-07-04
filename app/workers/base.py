from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

InputT = TypeVar("InputT", bound=dict[str, Any])
ResultT = TypeVar("ResultT", bound=dict[str, Any])


class BaseJobHandler(ABC, Generic[InputT, ResultT]):
    """
    Contract that every worker type must follow.

    Python Internals Focus:
    -----------------------
    - ABC (Abstract Base Class): forces subclasses to implement all @abstractmethod.
      If a subclass forgets one, Python raises TypeError at *class creation time*.
    - Generic[InputT, ResultT]: parameterizes the handler with specific input/output types.
      This is a *type-level* concept — no runtime cost, but editors and mypy use it.
    - TypeVar with bound: constrains T to be a dict subtype, so you can't accidentally
      pass an int where a dict is expected.

    DSA Focus:
    ----------
    Each subclass will implement a different DSA concept in its process() method:
    - Summarization: chunking + sliding window
    - Embeddings: vectors + cosine similarity + nearest neighbor
    - OCR: batch processing pipeline
    - Transcription: interval merging + timestamp alignment
    - Recommendations: graph traversal + scoring with heaps
    """

    @abstractmethod
    def validate_input(self, input_payload: InputT) -> None:
        """
        Raise ValueError if input_payload is invalid for this job type.
        Called BEFORE process() — fail fast, don't waste compute.
        """
        ...

    @abstractmethod
    def process(self, input_payload: InputT) -> ResultT:
        """
        Do the actual work. This is where DSA concepts live.
        Must return a JSON-serializable dict.
        """
        ...

    @abstractmethod
    def format_result(self, raw_result: ResultT) -> dict[str, Any]:
        """
        Post-process / normalize the raw result into the final shape
        stored in result_payload. Useful for stripping internal metadata,
        rounding floats, etc.
        """
        ...

    def run(self, input_payload: InputT) -> dict[str, Any]:
        """
        Template method pattern: validate → process → format.
        Subclasses override the steps, not run() itself.
        """
        self.validate_input(input_payload)
        raw = self.process(input_payload)
        return self.format_result(raw)