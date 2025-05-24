from pydantic import BaseModel
from datetime import datetime

class GnssDataSchema(BaseModel):
    timestamp: datetime
    lat: float
    lon: float
    h_msl: float
    fix_type: int
    carr_soln: int
    gnss_fix_ok: bool
