"""PrescpHealth Backend — Task Status Exceptions."""


class TaskStatusError(Exception):
    """Base exception for task-status module errors."""

    def __init__(self, message: str = "Task status error") -> None:
        """
        Args:
            message: Human-readable error description.
        """
        self.message = message
        super().__init__(self.message)


class TaskNotFoundError(TaskStatusError):
    """Raised when a background task cannot be found for the current tenant."""

    def __init__(self, task_id: str) -> None:
        """
        Args:
            task_id: UUID string of the missing task.
        """
        super().__init__(f"Background task not found: {task_id}")
