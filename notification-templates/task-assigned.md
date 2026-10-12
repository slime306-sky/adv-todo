---
subject: "Task assigned: {{ task.title }}"
---

# A task has been assigned to you

Hello {{ recipient.username }},

{{ assigned_by.username }} has assigned you a task.

- **Task:** {{ task.title }}
- **Task ID:** {{ task.id }}

## Description

{{ task.description }}

## Subtasks

{% if subtasks %}
{% for subtask in subtasks %}
- **{{ subtask.title }}** (ID: {{ subtask.id }})
  - {{ subtask.description }}
  - Estimated time: {{ subtask.estimated_days }} days, {{ subtask.estimated_hours }} hours
{% endfor %}
{% else %}
No subtasks were included.
{% endif %}

Please open todo to view the task and begin working.

— TMS