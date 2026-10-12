---
subject: "Subtask completed: {{ subtask.title }}"
---

# Subtask completed

Hello {{ recipient.username }},

A subtask has been marked as complete.

- **Task:** {{ task.title }} (ID: {{ task.id }})
- **Subtask:** {{ subtask.title }} (ID: {{ subtask.id }})
- **Completed by:** {{ completed_by.username }}

Please open todo to review the task's progress.

— TMS