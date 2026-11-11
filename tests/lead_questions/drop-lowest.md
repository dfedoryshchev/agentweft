HANDOFF
DID:
- Planned `report --drop-lowest N` as behaviours a test can check. None contradicts TASK.md, so there is no CONFLICT line
QUESTION: How should `--drop-lowest` combine with `--missing exclude`: are the N lowest picked among all weight>0 assessments with missing as 0, with exclude then removing the remaining missing ones? (TASK.md:141)
RECOMMEND: Pick among all weight>0 assessments with missing as 0, then exclude the remaining missing ones; this follows the request's "a missing score counts as 0 for this choice" and keeps the bound tied to the config
SIZE: one function in gradebook/commands.py, plus one TASK.md line
END HANDOFF
