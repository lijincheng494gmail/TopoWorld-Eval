# Small executable examples

`synthetic_two_rooms.json` declares two room regions and a hosted door opening. `synthetic_blocked_door.json` uses the same geometry with an obstacle filling that aperture. The fixed query asks whether the door connects the two rooms.

Run `python scripts/check_example.py` from the repository root. The expected readouts are TRUE and FALSE. These examples were constructed to demonstrate the released evaluator; they are software fixtures and are not additional buildings, model outputs, or benchmark results.

The complete Release contains historical real model outputs, prompts, drawings, and references for the reported study.
