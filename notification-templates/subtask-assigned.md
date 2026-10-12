---
subject: "New subtask assigned: {{ subtask.title }}"
---

# You have been assigned a new subtask!

Hello {{ recipient.username }},

A new subtask has been assigned to you.

**Subtask:** {{ subtask.title }}

**Parent task:** {{ task.title }}

**Description:** {{ subtask.description }}

**Assigned by:** {{ assigned_by.username }}

**Subtask ID:** {{ subtask.id }}

Please log in to your task management system to view the details.