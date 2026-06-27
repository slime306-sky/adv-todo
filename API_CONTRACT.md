# API Contract

This document lists the current endpoints, descriptions, sample request payloads, and expected responses.

**Auth**

- POST /register
  - Description: Create a new user. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {
      "username": "jdoe",
      "email": "jdoe@example.com",
      "password": "secret",
      "role": "user"
    }
    ```
  - Success response:
    ```json
    {"message": "User created"}
    ```

- POST /login
  - Description: Obtain a JWT access token.
  - Auth: None
  - Request payload:
    ```json
    {"username": "jdoe", "password": "secret"}
    ```
  - Success response:
    ```json
    {
      "access_token": "<token>",
      "token_type": "bearer",
      "username": "jdoe",
      "role": "user",
      "user": {"id": 1, "name": "jdoe"}
    }
    ```

- POST /change-password
  - Description: Change the current user's password.
  - Auth: Bearer token
  - Request payload:
    ```json
    {"current_password": "old", "new_password": "newsecret"}
    ```
  - Success response:
    ```json
    {"message": "Password changed successfully"}
    ```

**Users**

- GET /users
  - Description: List all users. Admin only.
  - Auth: Admin
  - Response:
    ```json
    [
      {"id": 1, "name": "jdoe", "email": "jdoe@example.com", "role": "user", "departments": []}
    ]
    ```

- PUT /users/{user_id}
  - Description: Update user fields, but not password. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {"email": "new@example.com", "role": "user"}
    ```
  - Success response:
    ```json
    {"id": 1, "name": "jdoe", "email": "new@example.com", "role": "user", "departments": []}
    ```

- POST /users/remediate-passwords
  - Description: Remediate legacy plaintext passwords. Admin only.
  - Auth: Admin
  - Query params: `dry_run=true|false`, `limit=100`
  - Success response:
    ```json
    {
      "processed_users": 2,
      "affected_users": [
        {"user_id": 2, "username": "x", "email": "x@e", "temporary_password": "..."}
      ]
    }
    ```

- DELETE /users/{user_id}
  - Description: Delete a user. Admin cannot delete themselves.
  - Auth: Admin
  - Success response:
    ```json
    {"message": "User deleted successfully"}
    ```

**Departments**

- POST /departments
  - Description: Create a department.
  - Auth: Admin
  - Request payload:
    ```json
    {"name": "Engineering"}
    ```
  - Success response:
    ```json
    {"id": 1, "name": "Engineering", "user_count": 0}
    ```

- GET /departments
  - Description: List departments with member counts.
  - Auth: Any authenticated user
  - Success response:
    ```json
    [{"id": 1, "name": "Engineering", "user_count": 3}]
    ```

- PUT /users/{user_id}/departments
  - Description: Assign departments to a user.
  - Auth: Admin
  - Request payload:
    ```json
    {"department_ids": [1, 2]}
    ```
  - Success response:
    ```json
    {"message": "User departments updated", "department_ids": [1, 2]}
    ```

**Dashboard**

- GET /dashboard
  - Description: Returns aggregated task counts and recent tasks for the current user. Admins see all tasks.
  - Auth: Any authenticated user
  - Success response:
    ```json
    {
      "total_tasks": 10,
      "completed_tasks": 2,
      "in_progress_tasks": 3,
      "pending_tasks": 5,
      "overdue": 1,
      "recent_tasks": [
        {"id": 1, "title": "Task 1", "status": "not_complete", "created_by": {"id": 1, "name": "jdoe"}}
      ]
    }
    ```

- GET /timeline
  - Description: Admin-only task summary list for timeline and overview cards.
  - Auth: Admin
  - Success response:
    ```json
    {
      "items": [
        {
          "id": 11,
          "title": "Build API",
          "start_date": "2026-06-01T00:00:00Z",
          "end_date": "2026-06-05T00:00:00Z",
          "assignee": {"id": 1, "name": "udayshah"},
          "sub_task_count": 4,
          "completed_sub_task_count": 2,
          "total_estimated_hours": 24,
          "total_actual_hours": 18,
          "total_elapsed_hours": 19.5,
          "total_expected_completion_hours": 17.25
        }
      ]
    }
    ```

- GET /tasks/{task_id}/progress
  - Description: Returns completion progress for a task.
  - Auth: Any authenticated user with access to the task.
  - Success response:
    ```json
    {
      "task_id": 11,
      "total_subtasks": 4,
      "completed_subtasks": 2,
      "progress_percentage": 50,
      "is_completed": false
    }
    ```

- GET /tasks/{task_id}/timeline
  - Description: Returns estimated, actual, and expected timing breakdown for a task.
  - Auth: Any authenticated user with access to the task.
  - Notes: `total_expected_hours` counts completed sub-tasks only. For priority-based tasks, the completed sub-task expected hours are weighted by `priority` (`weightage_priority`).
  - Success response:
    ```json
    {
      "task_id": 11,
      "task_title": "Build API",
      "start_date": "2026-06-01T00:00:00Z",
      "end_date": "2026-06-05T00:00:00Z",
      "total_estimated_hours": 24,
      "total_actual_hours": 18,
      "total_expected_hours": 17.25,
      "bars": [
        {"key": "estimated", "label": "How much time it will take", "hours": 24, "percentage": 100},
        {"key": "actual", "label": "How much time user took", "hours": 18, "percentage": 75},
        {"key": "expected", "label": "How much time it should have taken", "hours": 17.25, "percentage": 71.88}
      ],
      "sub_tasks": []
    }
    ```

**Audit Logs**

- GET /audit-logs
  - Description: List audit logs. Admins can query all logs; non-admins see their own logs only.
  - Auth: Any authenticated user
  - Query filters: `action`, `entity_type`, `entity_id`, `user_id`, `search`, `start_date`, `end_date`, `page`, `page_size`
  - Success response:
    ```json
    {
      "items": [
        {
          "id": 1,
          "action": "CREATE",
          "entity_type": "task",
          "entity_id": 1,
          "message": "Task created",
          "details": {},
          "user_id": 1,
          "user": {"id": 1, "name": "jdoe"},
          "created_at": "..."
        }
      ],
      "total": 1,
      "page": 1,
      "page_size": 20,
      "total_pages": 1
    }
    ```

**Tasks**

- POST /tasks
  - Description: Create a task.
  - Auth: Authenticated user
  - Request payload:
    ```json
    {
      "title": "New Task",
      "description": "Details",
      "non_priority_flag": false,
      "sub_tasks": [
        {
          "title": "Sub 1",
          "description": "...",
          "estimated_days": 1,
          "estimated_hours": 2,
          "assigned_to": 2,
          "weightage_priority": 50,
          "subtask_priority": "high"
        }
      ]
    }
    ```
  - Creation paths:
    - Admins create tasks directly, including priority tasks.
    - Non-admins create non-priority tasks directly when `non_priority_flag` is `true`.
    - Non-admins creating priority tasks create the task immediately when every sub-task includes both `weightage_priority` and `subtask_priority`.
    - Non-admins creating priority tasks still receive a pending task creation request when no sub-task priority values are provided.
    - Mixed, partial, or null sub-task priority input is rejected with validation error.
  - Responses:
    - Immediate create:
      ```json
      {
        "id": 1,
        "title": "New Task",
        "description": "Details",
        "non_priority_flag": false,
        "status": "not_complete",
        "estimated_days": 5,
        "estimated_hours": 16,
        "start_date": "2026-06-26T00:00:00Z",
        "end_date": "2026-07-01T16:00:00Z",
        "created_by": {"id": 1, "name": "jdoe"},
        "department": null,
        "version": "1.0.0",
        "parent_task_id": null,
        "sub_tasks": [{"id": 5, "title": "Sub 1", "task_id": 1}],
        "sub_tasks_created_count": 1
      }
      ```
    - Priority creation request:
      ```json
      {
        "id": 1,
        "requested_by": {"id": 1, "name": "jdoe"},
        "status": "pending",
        "requested_payload": {},
        "review_comment": null,
        "reviewed_by": null,
        "approved_task_id": null,
        "created_at": "...",
        "reviewed_at": null
      }
      ```
    - Approved request outcome: the admin review endpoint creates the task from the stored payload and returns the task creation request in approved state with `approved_task_id` set.
    - Approved requests can preserve user-supplied sub-task priority values or let the admin adjust them before approval.

- GET /my-tasks
  - Description: List tasks for the current user, either created by them or assigned to them.
  - Auth: Authenticated user
  - Query: `page`, `page_size`, `search`, `status`
  - Success response: paginated task list with sub-tasks.

- GET /tasks
  - Description: Admin list of all tasks.
  - Auth: Admin
  - Query: `page`, `page_size`, `search`, `status`
  - Success response: paginated task list.

- GET /tasks/{task_id}
  - Description: Get task details including sub-tasks.
  - Auth: Authenticated user
  - Success response: task object with `sub_tasks`.

- PUT /tasks/{task_id}
  - Description: Update a task. Non-admins create update requests unless the task remains non-priority.
  - Auth: Authenticated user
  - Request payload:
    ```json
    {"title": "Updated title", "non_priority_flag": true}
    ```
  - Success response: updated task object.

- PUT /tasks/{task_id}/complete
  - Description: Mark task complete.
  - Auth: Authenticated user with task manage rights
  - Success response:
    ```json
    {"message": "Task marked complete"}
    ```

- POST /tasks/{task_id}/revise
  - Description: Create a new version of a completed task.
  - Auth: Admin
  - Request payload:
    ```json
    {"bump_type": "minor"}
    ```
  - Success response: new task object with incremented version and `parent_task_id` set.

- PUT /tasks/{task_id}/subtasks/priorities
- POST /tasks/{task_id}/subtasks/priorities
  - Description: Bulk-update all sub-task priorities. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {
      "items": [
        {"sub_task_id": 5, "weightage_priority": 50},
        {"sub_task_id": 6, "weightage_priority": 50}
      ]
    }
    ```
  - Success response:
    ```json
    {"task_id": 1, "total_priority": 100, "items": [{"sub_task_id": 5, "weightage_priority": 50}]}
    ```

- GET /task-creation-requests/my
  - Description: List task creation requests made by the current user.
  - Auth: Authenticated user
  - Success response: paginated list of task creation requests.

- GET /task-creation-requests
  - Description: List all task creation requests. Admin only.
  - Auth: Admin
  - Query params: `status`, `page`, `page_size`
  - Success response: paginated list of task creation requests.

- PUT /task-creation-requests/{request_id}/approve
  - Description: Approve a pending task creation request. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {
      "comment": "Approved",
      "approved_payload": {
        "non_priority_flag": false,
        "sub_tasks": [
          {"temporary_subtask_id": "abc", "weightage_priority": 50, "subtask_priority": "high"}
        ]
      }
    }
    ```
  - Success response: task creation request object with approved status and `approved_task_id`.

- PUT /task-creation-requests/{request_id}/reject
  - Description: Reject a pending task creation request. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {"comment": "Not approved"}
    ```
  - Success response: task creation request object with rejected status.

- GET /task-update-requests/my
  - Description: List task update requests made by the current user.
  - Auth: Authenticated user
  - Success response: paginated list of task update requests.

- GET /task-update-requests
  - Description: List all task update requests. Admin only.
  - Auth: Admin
  - Query params: `status`, `page`, `page_size`
  - Success response: paginated list of task update requests.

- PUT /task-update-requests/{request_id}/approve
  - Description: Approve a pending task update request. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {"comment": "Approved"}
    ```
  - Success response: task update request object with approved status.

- PUT /task-update-requests/{request_id}/reject
  - Description: Reject a pending task update request. Admin only.
  - Auth: Admin
  - Request payload:
    ```json
    {"comment": "Rejected"}
    ```
  - Success response: task update request object with rejected status.

- DELETE /tasks/{task_id}
  - Description: Delete a task. Admin only.
  - Auth: Admin
  - Success response:
    ```json
    {"message": "Task deleted successfully"}
    ```

**Sub Tasks**

- POST /subtasks
  - Description: Create a sub-task for a task.
  - Auth: Authenticated user with manage rights on the task.
  - Request payload:
    ```json
    {
      "title": "Design schema",
      "description": "Create initial tables",
      "status": "not_complete",
      "weightage_priority": 50,
      "subtask_priority": "high",
      "estimated_days": 1,
      "estimated_hours": 8,
      "start_date": "2026-06-01T00:00:00Z",
      "task_id": 11,
      "assigned_to": 2
    }
    ```
  - Response: sub-task object with computed timing fields

- GET /subtasks
  - Description: List sub-tasks visible to the current user.
  - Auth: Authenticated user
  - Query: `page`, `page_size`, `search`, `status`, `task_id`

- GET /subtasks/{sub_task_id}
  - Description: Get a sub-task by id.
  - Auth: Authenticated user with access to the parent task.

- PUT /subtasks/{sub_task_id}
  - Description: Update a sub-task.
  - Auth: Authenticated user with access to the parent task.

- PUT /subtasks/{sub_task_id}/complete
  - Description: Mark a sub-task complete and auto-fill actual time.
  - Auth: Authenticated user with access to the parent task.

- GET /subtask-update-requests/my
  - Description: List sub-task update requests made by the current user.
  - Auth: Authenticated user

- GET /subtask-update-requests
  - Description: List all sub-task update requests.
  - Auth: Admin

- PUT /subtask-update-requests/{request_id}/approve
  - Description: Approve a pending sub-task update request.
  - Auth: Admin

- PUT /subtask-update-requests/{request_id}/reject
  - Description: Reject a pending sub-task update request.
  - Auth: Admin

- DELETE /subtasks/{sub_task_id}
  - Description: Delete a sub-task.
  - Auth: User with manage rights on the parent task, admin permitted.
  - Response:
    ```json
    {"message": "Sub task deleted successfully"}
    ```

**Activities**

- POST /activities
  - Description: Create an activity on a sub-task.
  - Auth: Authenticated user with access to the parent task.
  - Request payload:
    ```json
    {"title": "Code review", "description": "Review the schema changes", "note": "Add comments", "date": "2026-06-26", "sub_task_id": 5}
    ```

- PUT /activities/{activity_id}
  - Description: Update an activity.
  - Auth: Admin

- DELETE /activities/{activity_id}
  - Description: Delete an activity.
  - Auth: Admin

- GET /tasks/{task_id}/activities
  - Description: List activities for a task.
  - Auth: Authenticated user with access to the task.
  - Query: `page`, `page_size`, `search`, `status`, `sub_task_id`

- GET /tasks/{task_id}/timeline
  - Description: Get task timeline summary for chart rendering.
  - Auth: Authenticated user
  - Response: task timeline with bars and sub-task timing breakdown, including task `start_date` and `end_date`
  - Notes: `total_expected_hours` counts completed sub-tasks only. For priority-based tasks, the completed sub-task expected hours are weighted by `priority` (`weightage_priority`).
  - Response example:
    ```json
    {
      "task_id": 11,
      "task_title": "Build API",
      "start_date": "2026-06-01T00:00:00Z",
      "end_date": "2026-06-05T00:00:00Z",
      "total_estimated_hours": 24,
      "total_actual_hours": 20,
      "total_expected_hours": 18,
      "bars": [
        {"key": "estimated", "label": "How much time it will take", "hours": 24, "percentage": 100},
        {"key": "actual", "label": "How much time user took", "hours": 20, "percentage": 83.33},
        {"key": "expected", "label": "How much time it should have taken", "hours": 18, "percentage": 75}
      ],
      "sub_tasks": [
        {
          "sub_task_id": 101,
          "title": "Design models",
          "status": "complete",
          "priority": 50,
          "estimated_hours": 10,
          "actual_hours": 8,
          "expected_hours": 12,
          "start_date": "2026-06-01T00:00:00Z",
          "end_date": "2026-06-02T00:00:00Z"
        }
      ]
    }
    ```

**Task Creation & Update Requests**

- GET /task-creation-requests/my
  - Description: List my task creation requests.
  - Auth: Authenticated user
  - Response: paginated list of requests

- GET /task-creation-requests
  - Description: Admin list of all task creation requests.
  - Auth: Admin

- PUT /task-creation-requests/{request_id}/approve
  - Description: Approve a pending task creation request (admin).
  - Auth: Admin
  - Payload example:
    ```json
    {"approved_payload": {"non_priority_flag": false, "sub_tasks": []}, "comment": "Approved"}
    ```
  - Response: the task creation request object with `approved_task_id` set

- PUT /task-creation-requests/{request_id}/reject
  - Description: Reject with required comment (admin).
  - Auth: Admin
  - Payload:
    ```json
    {"comment": "Reason for rejection"}
    ```
  - Response: request object updated with rejection

- GET /task-update-requests/my and /task-update-requests
  - Description: Similar to creation requests but for updates.
  - Approve/reject endpoints: `/task-update-requests/{request_id}/approve` and `/.../reject` (admin)

**Sub-tasks**

- POST /subtasks
  - Description: Create a sub-task. Non-admins may create and trigger approval requests for missing priority fields.
  - Auth: Authenticated user
  - Payload example:
    ```json
    {
      "title":"Sub 1",
      "description":"...",
      "task_id": 1,
      "estimated_days":1,
      "estimated_hours":2,
      "assigned_to":2,
      "weightage_priority":50,
      "subtask_priority":"medium"
    }
    ```
  - Response: created sub-task object

- GET /subtasks
  - Description: List sub-tasks (admin sees all, users restricted to their tasks/assignments).
  - Query: `page`, `page_size`, `search`, `status`, `task_id`
  - Response: paginated list

- GET /subtasks/{sub_task_id}
  - Description: Get single sub-task (requires access)
  - Response: sub-task object

- PUT /subtasks/{sub_task_id}
  - Description: Update a sub-task. Non-admins may create an update request when priority fields are affected.
  - Auth: Authenticated user
  - Payload: partial `SubTaskUpdate` fields
  - Response: updated sub-task or task snapshot if request created

- DELETE /subtasks/{sub_task_id}
  - Description: Delete a sub-task (user must have manage rights)
  - Response:
    ```json
    {"message":"Sub task deleted successfully"}
    ```

- Sub-task update requests endpoints: `/subtask-update-requests/my`, `/subtask-update-requests`, and approve/reject at `/subtask-update-requests/{id}/approve` and `/.../reject` (admin)

**Activities**

- POST /activities
  - Description: Create an activity for a sub-task. Any authenticated user can create.
  - Auth: Any authenticated user
  - Payload:
    ```json
    {"title":"Work done","description":"...","note":"extra detail","date":"2026-01-01","sub_task_id":5}
    ```
  - Response: created activity object with `note`

- PUT /activities/{activity_id}
  - Description: Update an activity (admin only).
  - Response: updated activity object

- DELETE /activities/{activity_id}
  - Description: Delete activity (admin only).
  - Response: message on success

- GET /tasks/{task_id}/activities
  - Description: List activities for a task (user must have manage rights)
  - Query: `page`, `page_size`, `search`, `status`, `sub_task_id`
  - Response: paginated activities


---
Notes:
- All endpoints requiring authentication expect a Bearer token in `Authorization: Bearer <token>` header.
- Many endpoints enforce admin role via `require_role("admin")`. The summary above indicates those cases.
- Request/response examples are representative of payload shapes used in code; minor schema field names/types may vary (see app/schemas for exact Pydantic models).
