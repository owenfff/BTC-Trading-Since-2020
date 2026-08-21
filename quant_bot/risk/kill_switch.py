from __future__ import annotations


class KillSwitch:
    def __init__(self) -> None:
        self.engaged = True

    def engage(self) -> None:
        self.engaged = True

    def disengage(self, *, human_approved: bool) -> None:
        if not human_approved:
            raise PermissionError("kill switch requires explicit human approval")
        self.engaged = False
