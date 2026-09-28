"""Compatibility import for the pre-MVP BMSTU-only retry executor."""

from .ingestion_retry import SqlAlchemyIngestionRetryExecutor

SqlAlchemyBmstuIngestionRetryExecutor = SqlAlchemyIngestionRetryExecutor

__all__ = ["SqlAlchemyBmstuIngestionRetryExecutor"]
