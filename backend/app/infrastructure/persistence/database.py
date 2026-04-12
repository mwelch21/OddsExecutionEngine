from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseSessionFactory:
    def __init__(self, database_url: str) -> None:
        connect_args: dict[str, object] = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self._engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._sessionmaker = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            future=True,
            class_=Session,
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_session(self) -> Session:
        return self._sessionmaker()
