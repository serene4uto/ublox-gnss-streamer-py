from pydantic import BaseModel
from datetime import datetime
from typing import Literal

class GnssDataSchema(BaseModel):
    timestamp: datetime
    lat: float
    lon: float
    alt: float
    type: Literal[
        'extrapolated',     # Extrapolated data, not a real GNSS fix
        'no-fix',           # No GNSS fix available
        'no-rtk',           # Standard GNSS fix, no RTK
        'float-rtk',        # RTK float solution
        'fixed-rtk',        # RTK fixed solution
        'dead-reckoning'    # Dead reckoning or combined solution
    ]
