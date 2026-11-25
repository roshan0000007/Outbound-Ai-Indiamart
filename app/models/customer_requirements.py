"""
Customer Requirements Model
Data structure for storing customer business requirements
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class CustomerRequirement(Base):
    """Customer requirement record model"""
    __tablename__ = "customer_requirements"

    id = Column(Integer, primary_key=True)
    call_id = Column(String(64), unique=True, nullable=False, index=True)
    customer_name = Column(String(100), nullable=True)
    company_name = Column(String(150), nullable=True)
    location = Column(String(100), nullable=True)
    interested_products = Column(Text, nullable=True)  # Comma-separated
    required_quantity = Column(Text, nullable=True)
    business_requirement = Column(Text, nullable=True)
    bulk_and_other_requirements = Column(Text, nullable=True)
    
    # Metadata
    is_complete = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source = Column(String(50), default="call")  # call, manual, api, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "call_id": self.call_id,
            "customer_name": self.customer_name,
            "company_name": self.company_name,
            "location": self.location,
            "interested_products": self.interested_products,
            "required_quantity": self.required_quantity,
            "business_requirement": self.business_requirement,
            "bulk_and_other_requirements": self.bulk_and_other_requirements,
            "is_complete": self.is_complete,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
