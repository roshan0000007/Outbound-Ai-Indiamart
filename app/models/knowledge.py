"""
Knowledge Base Data Models
Database models for knowledge sources and documents
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
