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


class TranscriptionProgress(Base):
    """Durable checkpoint committed together with each batch of new cues."""

    __tablename__ = "transcription_progress"
    project_id = Column(String, ForeignKey("projects.id"), primary_key=True)
    next_start = Column(Integer, nullable=False, default=0)
    completed = Column(Integer, nullable=False, default=0)


class TaskControl(Base):
    """The resumable operation associated with a paused or cancelled project."""

    __tablename__ = "task_controls"
    project_id = Column(String, ForeignKey("projects.id"), primary_key=True)
    kind = Column(String, nullable=False)
    backup_id = Column(String, nullable=True)


class CueReview(Base):
    """Non-destructive review metadata and optional improvement proposal."""

    __tablename__ = "cue_reviews"
    cue_id = Column(String, ForeignKey("cues.id"), primary_key=True)
    flag = Column(String, nullable=True)
    flag_resolved = Column(Integer, nullable=False, default=0)
    proposal = Column(Text, nullable=True)
    proposal_source = Column(Text, nullable=True)


class ComparisonSnapshot(Base):
    """Recoverable pre- and post-comparison state, including deleted cues."""

    __tablename__ = "comparison_snapshots"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    changes = Column(Text, nullable=False)
    created = Column(Float, nullable=False)
    restored = Column(Integer, nullable=False, default=0)


class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(String, primary_key=True)
    config = Column(Text, nullable=False)
    created = Column(Float, nullable=False)


class Batch(Base):
    __tablename__ = "batches"
    id = Column(String, primary_key=True)
    recipe_id = Column(String, ForeignKey("recipes.id"), nullable=False)
    recipe = Column(Text, nullable=False)
    paused = Column(Integer, nullable=False, default=0)
    created = Column(Float, nullable=False)


class BatchItem(Base):
    __tablename__ = "batch_items"
    id = Column(String, primary_key=True)
    batch_id = Column(String, ForeignKey("batches.id"), nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="queued")
    stage = Column(String, nullable=False, default="source")
    error = Column(Text, nullable=False, default="")
    improvement_id = Column(String, nullable=True)
