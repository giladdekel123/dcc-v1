from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    locator: str   # where in the file: "page 2", 'section "Query"', "table 2, row 4", 'sheet "X", rows 1-16'
    body: str
