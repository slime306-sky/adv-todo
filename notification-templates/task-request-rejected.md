---
subject: "Task request rejected: {{ task.title }}"
---

# Your task request was rejected

Hello {{ recipient.username }},

Your task request was reviewed and rejected.

- **Request ID:** {{ request.id }}
- **Task:** {{ task.title }}
- **Reviewed by:** {{ reviewed_by.username }}

## Reason / review comment

{{ comment }}

If you need clarification, please contact the administrator.

— TMS