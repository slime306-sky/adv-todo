---
subject: "[adv-todo] Activity logged: {{ activity.title }}"
---

# New activity logged

Hello {{ recipient.username }},

A user has logged an activity in adv-todo.

- **Activity:** {{ activity.title }}
- **Task:** {{ task.title }} (ID: {{ task.id }})
- **Subtask:** {{ subtask.title }} (ID: {{ subtask.id }})
- **Logged by:** {{ created_by.username }}

Please open the dashboard to review the activity details.

— TMS