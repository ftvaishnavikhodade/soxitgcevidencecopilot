from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from datetime import datetime
from sqlalchemy.orm import relationship
from database import Base

class Control(Base):
    __tablename__ = "controls"

    id = Column(Integer, primary_key=True, index=True)
    description = Column(Text, nullable=False)
    test_procedure = Column(Text, nullable=False)

    test_runs = relationship("TestRun", back_populates="control", cascade="all, delete-orphan")

class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("controls.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Store JSON string of file paths
    files_json = Column(Text, nullable=True)
    
    # Analysis Results
    status = Column(String, default="Pending") # Pending, Analyzed, Error
    summary = Column(Text, nullable=True) # General summary of files
    checklist_json = Column(Text, nullable=True) # JSON structured checklist results
    rating = Column(String, nullable=True) # Likely Sufficient, Insufficient, Unclear
    issues = Column(Text, nullable=True) # List of issues found
    workpaper = Column(Text, nullable=True) # Draft workpaper text

    control = relationship("Control", back_populates="test_runs")
