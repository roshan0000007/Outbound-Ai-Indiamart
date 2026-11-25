"""
Conversation History Models
Database models for call conversations
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ConversationMessage(Base):
    """Conversation message model"""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True)
    message_id = Column(String(64), unique=True, nullable=False)
    call_id = Column(String(64), nullable=False)
    sender = Column(String(20), nullable=False)
    message_text = Column(Text, nullable=False)
    language = Column(String(10), default="en")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "call_id": self.call_id,
            "sender": self.sender,
            "message_text": self.message_text,
            "language": self.language,
            "created_at": self.created_at.isoformat(),
        }

class ConversationSummary(Base):
    """Conversation summary model"""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True)
    call_id = Column(String(64), unique=True, nullable=False)
    total_messages = Column(Integer, default=0)
    user_messages = Column(Integer, default=0)
    ai_messages = Column(Integer, default=0)
    summary_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

