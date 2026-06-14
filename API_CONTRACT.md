# API Contract

This document lists all endpoints, descriptions, sample request payloads, and expected responses.

**Auth**

- POST /register
  - Description: Create a new user (admin only).
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
  - Description: Obtain JWT access token.
  - Auth: None
  - Request payload:
    ```json
    {"username": "jdoe", "password": "secret"}
    ```
  - Success response (200):
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
  - Description: Change password for current user.
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
  - Description: List all users (admin only).
  - Auth: Admin
  - Query: none
  - Success response: list of users
    ```json
    [
      {"id": 1, "name": "jdoe", "email": "jdoe@example.com", "role": "user", "departments": []}
    ]
    ```

- PUT /users/{user_id}
  - Description: Update user fields (admin only, not password).
  - Auth: Admin
  - Request payload (example):
    ```json
    {"email": "new@example.com", "role": "user"}
    ```
  - Success response: updated user
    ```json
    {"id": 1, "name": "jdoe", "email": "new@example.com", "role": "user", "departments": []}
    ```

- POST /users/remediate-passwords
  - Description: Remediate legacy plaintext passwords (admin).
  - Auth: Admin
  - Query params: `dry_run=true|false`, `limit=100`
  - Success response:
    ```json
    {"processed_users": 2, "affected_users": [{"user_id":2,"username":"x","email":"x@e","temporary_password":"..."}]}
    ```

- DELETE /users/{user_id}
  - Description: Delete a user (admin). Admin cannot delete themselves.
  - Auth: Admin
  - Success response:
    ```json
    {"message": "User deleted successfully"}
    ```

**Departments**

- POST /departments
  - Description: Create department (admin only).
  - Auth: Admin
  - Payload:
    ```json
    {"name": "Engineering"}
    ```
  - Response:
    ```json
    {"id": 1, "name": "Engineering"}
    ```

- GET /departments
  - Description: List departments and count of each department how many members are in that.
  - Auth: Any authenticated user
  - Response: list

- PUT /users/{user_id}/departments
  - Description: Assign departments to a user (admin).
  - Auth: Admin
  - Payload:
    ```json
    {"department_ids": [1,2]}
    ```
  - Response:
    ```json
    {"message":"User departments updated","department_ids":[1,2]}
    ```

**Dashboard**

- GET /dashboard
  - Description: Returns aggregated counts and recent tasks for current user (admin sees all).
  - Auth: Any authenticated user
  - Response (example):
    ```json
    {
      "total_tasks": 10,
      "completed_tasks": 2,
      "in_progress_tasks": 3,
      "pending_tasks": 5,
      "overdue": 1,
      "recent_tasks": [{"id":1,"title":"Task 1","status":"not complete","created_by":{"id":1,"name":"jdoe"}}]
    }
    ```

- GET /timeline
  - Description: Admin-only task summary list for frontend cards or timeline views.
  - Auth: Admin
  - Response (example):
    ```json
    {
      "items": [
        {
          "id": 11,
          "title": "Build API",
          "start_date": "2026-06-01T00:00:00Z",
          "end_date": "2026-06-05T00:00:00Z",
          "assignee": {"id": 1, "name": "udayshah"},
          "sub_task_count": 4
        }
      ]
    }
    ```

**Audit Logs**

- GET /audit-logs
  - Description: List audit logs. Admin can query all, non-admins see their own logs only.
  - Auth: Any authenticated user
  - Query filters: `action`, `entity_type`, `entity_id`, `user_id`, `search`, `start_date`, `end_date`, `page`, `page_size`
  - Response (paginated list):
    ```json
    {"items": [{"id":1,"action":"CREATE","entity_type":"task","entity_id":1,"message":"Task created","details":{},"user_id":1,"user":{"id":1,"name":"jdoe"},"created_at":"..."}],"total":1,"page":1,"page_size":20,"total_pages":1}
    ```

**Tasks**

- POST /tasks
  - Description: Create a task. Non-admins may require approval for priority fields.
  - Auth: Authenticated user (admins create directly)
  - Payload (example):
    ```json
    {
      "title": "New Task",
      "description": "Details",
      "non_priority_flag": false,
      "sub_tasks": [
        {"title":"Sub 1","description":"...","estimated_days":1,"estimated_hours":2,"assigned_to":2,"weightage_priority":50,"subtask_priority":"high"}
      ]
    }
    ```
  - Responses:
    - If created immediately (admin or non-priority task): returns created task with `sub_tasks` array and `sub_tasks_created_count`.
      ```json
      {"id":1,"title":"New Task","description":"Details","status":"not complete","sub_tasks":[{"id":5,...}],"sub_tasks_created_count":1}
      ```
    - If non-admin and requires approval: returns a task creation request object `{id, requested_by, status, requested_payload, ...}`

- GET /my-tasks
  - Description: List tasks for current user (creator or assigned).
  - Auth: Authenticated user
  - Query: `page`, `page_size`, `search`, `status`
  - Response: paginated tasks with sub_tasks

- GET /tasks
  - Description: Admin list of all tasks (admin only).
  - Auth: Admin
  - Query: `page`, `page_size`, `search`, `status`

- GET /tasks/{task_id}
  - Description: Get task details including sub-tasks. User must have access.
  - Auth: Authenticated user
  - Response: task with `sub_tasks` list

- PUT /tasks/{task_id}
  - Description: Update a task. Non-admins create update requests unless updating non-priority fields only.
  - Auth: Authenticated user
  - Payload example (partial):
    ```json
    {"title": "Updated title", "non_priority_flag": true}
    ```
  - Responses:
    - If admin: returns updated task payload
    - If non-admin and requires approval: returns task snapshot and creates update request

- PUT /tasks/{task_id}/complete
  - Description: Mark task complete (user must have manage rights)
  - Auth: Authenticated user
  - Response:
    ```json
    {"message":"Task marked complete"}
    ```

- DELETE /tasks/{task_id}
  - Description: Delete a task (admin only).
  - Auth: Admin
  - Response:
    ```json
    {"message":"Task deleted successfully"}
    ```

- POST /tasks/{task_id}/revise
  - Description: Create a new version (bump) of a completed task (admin only).
  - Auth: Admin
  - Payload (optional):
    ```json
    {"bump_type": "minor"}
    ```
  - Response: new task object (new version)

- PUT/POST /tasks/{task_id}/subtasks/priorities
  - Description: Bulk-update sub-task priorities (admin only).
  - Auth: Admin
  - Payload:
    ```json
    {"items": [{"sub_task_id":5, "weightage_priority":50}, {"sub_task_id":6, "weightage_priority":50}]}
    ```
  - Response:
    ```json
    {"task_id":1, "total_priority":100, "items": [...]}
    ```

- GET /tasks/{task_id}/timeline
  - Description: Get task timeline summary for chart rendering.
  - Auth: Authenticated user
  - Response: task timeline with bars and sub-task timing breakdown, including task `start_date` and `end_date`
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
