from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

InputT = TypeVar("InputT", bound=dict[str, Any])
ResultT = TypeVar("ResultT", bound=dict[str, Any])


class BaseJobHandler(ABC, Generic[InputT, ResultT]):
    """Shared contract for job handlers: validate → process → format."""

    @abstractmethod
    def validate_input(self, input_payload: InputT) -> None:
        """Raise ValueError if the payload is invalid for this job type."""
        ...

    @abstractmethod
    def process(self, input_payload: InputT) -> ResultT:
        """Run the job and return a JSON-serializable result."""
        ...

    @abstractmethod
    def format_result(self, raw_result: ResultT) -> dict[str, Any]:
        """Normalize the result for storage in result_payload."""
        ...

    def run(self, input_payload: InputT) -> dict[str, Any]:
        """Execute validate → process → format."""
        self.validate_input(input_payload)
        raw = self.process(input_payload)
        return self.format_result(raw)
