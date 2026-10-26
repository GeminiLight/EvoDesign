"""
Workflow State Management for Baseline Direct LLM

This module defines the state structure used throughout the baseline workflow.
"""

from typing import Dict, Any, Optional, List


class WorkflowState:
    """State object for the baseline workflow.

    This class holds all the state information needed during the
    text-to-diagram conversion process, including input data,
    configuration, processing status, and output results.
    """

    def __init__(
        self,
        text_content: str,
        config: Optional[Dict[str, Any]] = None,
        user_query: str = "",
        **kwargs
    ):
        """Initialize workflow state.

        Args:
            text_content: Input text to convert to diagram
            config: Configuration dictionary with LLM and workflow settings
            user_query: User query or request text
            **kwargs: Additional state fields (metadata, intermediate results, etc.)
        """
        # Input data
        self.text_content = text_content
        self.user_query = user_query

        # Configuration
        self.config = config or {}

        # Processing status
        self.status = "initialized"  # initialized, processing, completed, failed

        # Error tracking
        self.errors: List[str] = []

        # Output data
        self.output: Optional[Dict[str, Any]] = None

        # Metadata and additional fields
        self.metadata: Dict[str, Any] = {}
        for key, value in kwargs.items():
            setattr(self, key, value)
            self.metadata[key] = value

    def add_error(self, error: str) -> None:
        """Add an error to the state.

        Args:
            error: Error message string
        """
        self.errors.append(error)
        if self.status != "failed":
            self.status = "failed"

    def get_errors(self) -> List[str]:
        """Get all errors from the state.

        Returns:
            List of error messages
        """
        return self.errors.copy()

    def has_errors(self) -> bool:
        """Check if the state has any errors.

        Returns:
            True if there are errors, False otherwise
        """
        return len(self.errors) > 0

    def is_completed(self) -> bool:
        """Check if the workflow completed successfully.

        Returns:
            True if status is completed, False otherwise
        """
        return self.status == "completed"

    def is_failed(self) -> bool:
        """Check if the workflow failed.

        Returns:
            True if status is failed, False otherwise
        """
        return self.status == "failed"

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary representation.

        Returns:
            Dictionary containing all state information
        """
        return {
            "status": self.status,
            "text_content": self.text_content,
            "user_query": self.user_query,
            "config": self.config,
            "errors": self.errors,
            "output": self.output,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        """String representation of the state.

        Returns:
            String representation showing status and key information
        """
        return (
            f"WorkflowState(status={self.status}, "
            f"errors={len(self.errors)}, "
            f"has_output={self.output is not None})"
        )
