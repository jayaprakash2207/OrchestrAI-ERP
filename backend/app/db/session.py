import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger("app.db")


class DatabaseManager:
    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    def initialize(self) -> None:
        if self._engine is not None and self._session_factory is not None:
            return

        logger.info(
            "Initializing PostgreSQL connection pool for host=%s port=%s db=%s pool_size=%s max_overflow=%s",
            settings.postgres_host,
            settings.postgres_port,
            settings.postgres_db,
            settings.db_pool_size,
            settings.db_max_overflow,
        )

        self._engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            echo=settings.log_sql_queries,
            connect_args={
                "connect_timeout": settings.db_connect_timeout,
                "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
            },
        )
        self._session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine,
            expire_on_commit=False,
        )

    @retry(
        stop=stop_after_attempt(settings.db_retry_attempts),
        wait=wait_exponential(
            multiplier=1,
            min=settings.db_retry_min_wait_seconds,
            max=settings.db_retry_max_wait_seconds,
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def ping(self) -> None:
        self.initialize()
        assert self._engine is not None
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("PostgreSQL connectivity check succeeded.")
        except OperationalError:
            logger.exception("PostgreSQL connectivity check failed.")
            raise

    def shutdown(self) -> None:
        if self._engine is not None:
            logger.info("Disposing PostgreSQL connection pool.")
            self._engine.dispose()
        self._engine = None
        self._session_factory = None

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        self.initialize()
        assert self._session_factory is not None
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Database session failed and was rolled back.")
            raise
        finally:
            session.close()

    def get_session(self) -> Generator[Session, None, None]:
        self.initialize()
        assert self._session_factory is not None
        session = self._session_factory()
        try:
            yield session
        except SQLAlchemyError:
            session.rollback()
            logger.exception("Database dependency session failed and was rolled back.")
            raise
        finally:
            session.close()


db_manager = DatabaseManager()


def get_db() -> Generator[Session, None, None]:
    yield from db_manager.get_session()
