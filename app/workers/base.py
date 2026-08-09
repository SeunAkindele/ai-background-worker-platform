from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

InputT = TypeVar("InputT", bound=dict[str, Any])
ResultT = TypeVar("ResultT", bound=dict[str, Any])


class BaseJobHandler(ABC, Generic[InputT, ResultT]):
    """Abstract contract for job handlers: validate → process → format."""

    @abstractmethod
    def validate_input(self, input_payload: InputT) -> None:
        """Raise ValueError if input_payload is invalid for this job type."""
        ...

    @abstractmethod
    def process(self, input_payload: InputT) -> ResultT:
        """Run the job and return a JSON-serializable result dict."""
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