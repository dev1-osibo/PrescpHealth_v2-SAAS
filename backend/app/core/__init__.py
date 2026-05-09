"""
PrescpHealth Backend — Core Infrastructure Package.

Contains shared infrastructure used across all modules:
- database.py: Async SQLAlchemy engine and session management
- base_model.py: Base model classes with tenant isolation mixin
- cache.py: Redis caching utilities (Task 1.4)
- middleware.py: Request middleware stack (Task 1.6)
- exceptions.py: Custom exception hierarchy (Task 1.7)
- events.py: Domain event bus (Task 1.8)
- pagination.py: Cursor-based pagination (Task 1.9)
- deps.py: FastAPI dependency injection helpers (Task 1.9)
"""
