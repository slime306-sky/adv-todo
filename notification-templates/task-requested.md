---
subject: "New task request #{{ request.id }}"
---

# New task request

Hello {{ recipient.username }},

A user has submitted a task request that needs your review.

- **Request ID:** {{ request.id }}
- **Task:** {{ request.title }}
- **Requested by:** {{ requested_by.username }}

Please open the admin dashboard to approve or reject this request.

— TMS