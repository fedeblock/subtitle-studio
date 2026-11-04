import os
import time
from sqlalchemy import create_engine, Column, String, Text, Float, Integer, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
from redis import Redis
from rq import Queue

DATA = os.environ.get("DATA_DIR", "/data")
Base = declarative_base()
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def initialize():
    for attempt in range(35):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except Exception:
            if attempt == 34:
                raise
            time.sleep(2)


def queue():
    return Queue("subtitles", connection=Redis.from_url(os.environ["REDIS_URL"]))


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    state = Column(String, default="queued")
    progress = Column(Integer, default=0)
    error = Column(Text, default="")
    language = Column(String, default="auto")
    created = Column(Float, nullable=False)


class Cue(Base):
    __tablename__ = "cues"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True)
    position = Column(Integer, nullable=False)
    start = Column(Float, nullable=False)
    end = Column(Float, nullable=False)
    original = Column(Text, nullable=False)
    translated = Column(Text, default="")


class HiddenProject(Base):
    __tablename__ = "hidden_projects"
    project_id = Column(String, ForeignKey("projects.id"), primary_key=True)
