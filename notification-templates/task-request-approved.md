---
subject: "[adv-todo] Task request approved: {{ task.title }}"
---

# Your task request was approved

Hello {{ recipient.username }},

Good news! Your task request has been approved.

- **Request ID:** {{ request.id }}
- **Task:** {{ task.title }}
- **Task ID:** {{ task.id }}
- **Reviewed by:** {{ reviewed_by.username }}

## Review comment

{{ comment }}

{% if subtasks %}
## Assigned subtasks

{% for subtask in subtasks %}
- **{{ subtask.title }}** (ID: {{ subtask.id }})
  - Assignee: {{ subtask.assignee }}
  - Estimate: {{ subtask.estimated_days }} days, {{ subtask.estimated_hours }} hours
{% endfor %}
{% endif %}

Please open adv-todo to view the full task details.

— TMS