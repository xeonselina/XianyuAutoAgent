"""
Knowledge base entry model.
Based on data-model.md specifications.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional


class KnowledgeEntry(BaseModel):
    """Knowledge base entry model."""
    
    # Basic information
    id: str = Field(..., description="Document unique ID")
    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Document content")
    
    # Classification
    category: Optional[str] = Field(None, description="Category tag")
    tags: List[str] = Field(default_factory=list, description="Tags list")
    
    # Metadata
    source: Optional[str] = Field(None, description="Source")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Business fields
    priority: int = Field(default=0, description="Priority for sorting (0-100)")
    active: bool = Field(default=True, description="Is active")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "kb_001",
                "title": "退款政策",
                "content": "用户在收到商品后7天内可申请无理由退款...",
                "category": "售后服务",
                "tags": ["退款", "售后"],
                "source": "官方文档",
                "priority": 10,
                "active": True
            }
        }
