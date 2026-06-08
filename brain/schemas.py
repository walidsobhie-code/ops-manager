from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class StoreReport(BaseModel):
    store_id: str
    report_date: datetime
    sales: float = 0.0
    inventory_status: Optional[str] = "Unknown"
    staffing: Optional[str] = "Unknown"
    analysis: Optional[str] = ""

class FleetKPIs(BaseModel):
    total_sales: float
    avg_sales: float
    store_count: int
    critical_count: int
    top_store_id: str
    top_store_sales: float

class AISummary(BaseModel):
    fleet_health_score: int = Field(..., ge=0, le=100)
    strategic_recommendation: str
    critical_alerts: List[str]
