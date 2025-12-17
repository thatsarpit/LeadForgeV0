from pydantic import BaseModel
from typing import Optional

class SlotStatus(BaseModel):
    slot_id: str
    status: str
    auto_resume: bool
    pid: Optional[int]
    last_heartbeat: Optional[str]