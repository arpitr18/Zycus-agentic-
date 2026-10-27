"""Application persistence; the original CSV/KB remain the source of ticket facts."""
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Float, Integer, Boolean, ForeignKey, JSON, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def now(): return datetime.now(timezone.utc).isoformat()
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(254),unique=True,index=True)
    name:Mapped[str]=mapped_column(String(100))
    password_hash:Mapped[str]=mapped_column(Text)
    role:Mapped[str]=mapped_column(String(20),default='support')
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    created_at:Mapped[str]=mapped_column(default=now)
class Assignment(Base):
    __tablename__='assignments'
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),primary_key=True)
    account_id:Mapped[str]=mapped_column(String(30),primary_key=True)
class SessionRecord(Base):
    __tablename__='sessions'
    token_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    csrf:Mapped[str]=mapped_column(String(100))
    expires_at:Mapped[float]=mapped_column(Float)
class Investigation(Base):
    __tablename__='investigations'
    id:Mapped[str]=mapped_column(String(50),primary_key=True)
    ticket_id:Mapped[str]=mapped_column(String(30),index=True)
    account_id:Mapped[str|None]=mapped_column(String(30),nullable=True,index=True)
    requested_by:Mapped[int]=mapped_column(ForeignKey('users.id'))
    status:Mapped[str]=mapped_column(String(20),default='queued',index=True)
    source:Mapped[str]=mapped_column(String(20),default='api')
    model:Mapped[str|None]=mapped_column(String(100),nullable=True)
    created_at:Mapped[str]=mapped_column(default=now,index=True)
    started_at:Mapped[str|None]=mapped_column(nullable=True)
    finished_at:Mapped[str|None]=mapped_column(nullable=True)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    seconds:Mapped[float|None]=mapped_column(Float,nullable=True)
    llm_calls:Mapped[int|None]=mapped_column(Integer,nullable=True)
    input_tokens:Mapped[int|None]=mapped_column(Integer,nullable=True)
    output_tokens:Mapped[int|None]=mapped_column(Integer,nullable=True)
    estimated_cost_usd:Mapped[float|None]=mapped_column(Float,nullable=True)
    pricing_snapshot:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    events:Mapped[list]=mapped_column(JSON,default=list)
    review_state:Mapped[str]=mapped_column(String(20),default='pending')
class Review(Base):
    __tablename__='reviews'
    id:Mapped[int]=mapped_column(primary_key=True)
    run_id:Mapped[str]=mapped_column(ForeignKey('investigations.id'),index=True)
    reviewer_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
    state:Mapped[str]=mapped_column(String(20))
    note:Mapped[str]=mapped_column(Text)
    overrides:Mapped[dict]=mapped_column(JSON,default=dict)
    created_at:Mapped[str]=mapped_column(default=now)
class Audit(Base):
    __tablename__='audits'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    action:Mapped[str]=mapped_column(String(80),index=True)
    target:Mapped[str]=mapped_column(String(200))
    detail:Mapped[dict]=mapped_column(JSON,default=dict)
    created_at:Mapped[str]=mapped_column(default=now)
class Setting(Base):
    __tablename__='settings'
    key:Mapped[str]=mapped_column(String(80),primary_key=True)
    value:Mapped[dict]=mapped_column(JSON)

def database(url=None):
    engine=create_engine(url or os.getenv('DATABASE_URL',f'sqlite:///{(ROOT/"data"/"platform.db").as_posix()}'),connect_args={'check_same_thread':False,'timeout':30})
    @event.listens_for(engine,'connect')
    def configure(conn,_):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
    Base.metadata.create_all(engine)
    return engine,sessionmaker(engine,expire_on_commit=False)
