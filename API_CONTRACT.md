# To-Do App API Contract

Version: 2.1.0
Generated from current implementation on 2026-04-03.

## 1. Service Overview

- Framework: FastAPI
- App entrypoint: app/main.py
- Local base URL: http://127.0.0.1:8000
- OpenAPI spec: GET /openapi.json
- Swagger UI: GET /docs

## 2. Authentication and Authorization

### 2.1 Token Type

- JWT Bearer token via OAuth2 password flow.
- Token endpoint: POST /login
- Token lifetime: 30 minutes

### 2.2 Authorization Header

Send on protected endpoints:

Authorization: Bearer <access_token>

### 2.3 Roles

- admin
- user

Route guards:

- admin-only routes use require_role("admin") and return 403 INSUFFICIENT_PERMISSIONS when not authorized.
- user-scoped routes validate ownership and return 403 FORBIDDEN_TASK_ACCESS when not authorized.

## 3. Error Contract

All non-2xx API errors are returned in this shape:

```json
{
  "message": "Human-readable message",
  "code": "MACHINE_READABLE_CODE",
  "dev_message": "Developer detail",
  "request_id": "uuid-or-incoming-x-request-id",
  "path": "/request/path",
  "details": []
}
```

Notes:

- details is present for validation errors and some custom errors.
- request_id is echoed in response header x-request-id.

### 3.1 Default Error Codes by Status

- 400 -> BAD_REQUEST
- 401 -> UNAUTHORIZED
- 403 -> FORBIDDEN
- 404 -> NOT_FOUND
- 409 -> CONFLICT
- 422 -> VALIDATION_ERROR
- 500 -> INTERNAL_SERVER_ERROR

### 3.2 Common Domain Error Codes

- USERNAME_ALREADY_EXISTS
- INVALID_CREDENTIALS
- INVALID_TOKEN
- INSUFFICIENT_PERMISSIONS
- INVALID_PASSWORD
- USER_NOT_FOUND
- SELF_ROLE_CHANGE_NOT_ALLOWED
- INVALID_ROLE
- PASSWORD_UPDATE_NOT_ALLOWED
- SELF_DELETE_NOT_ALLOWED
- ASSIGNED_USER_NOT_FOUND
- TASK_NOT_FOUND
- FORBIDDEN_TASK_ACCESS
- TASK_ALREADY_COMPLETE
- TASK_NOT_COMPLETE
- SUBTASK_NOT_FOUND
- SUBTASK_ALREADY_COMPLETE
- INVALID_SUBTASK_PRIORITY_TOTAL
- SUBTASKS_NOT_FOUND
- EMPTY_PRIORITY_PAYLOAD
- INCOMPLETE_PRIORITY_PAYLOAD
- DUPLICATE_SUBTASK_IN_PAYLOAD
- INVALID_SUBTASK_SET
- ACTIVITY_NOT_FOUND
- ACTIVITY_ALREADY_COMPLETE
- INVALID_ACTIVITY_STATUS
- TRANSACTION_FAILED

## 4. Shared DTO Shapes

### 4.1 UserReference

```json
{
  "id": 1,
  "name": "alice"
}
```

### 4.2 Pagination Envelope

Used by list endpoints:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10,
  "total_pages": 0
}
```

## 5. Endpoint Contract

## 5.1 Auth

### POST /register

Auth: admin required

Request body:

```json
{
  "username": "newuser",
  "email": "newuser@example.com",
  "password": "StrongPassword123",
  "role": "user"
}
```

Success 200:

```json
{
  "message": "User created"
}
```

Errors:

- 400 USERNAME_ALREADY_EXISTS
- 403 INSUFFICIENT_PERMISSIONS
- 422 VALIDATION_ERROR

### POST /login

Auth: none

Request body:

```json
{
  "username": "alice",
  "password": "StrongPassword123"
}
```

Success 200:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "username": "alice",
  "role": "user",
  "user": {
    "id": 2,
    "name": "alice"
  }
}
```

Errors:

- 401 INVALID_CREDENTIALS
- 422 VALIDATION_ERROR

### POST /change-password

Auth: authenticated user

Request body:

```json
{
  "current_password": "OldPassword123",
  "new_password": "NewPassword123"
}
```

Success 200:

```json
{
  "message": "Password changed successfully"
}
```

Errors:

- 400 INVALID_PASSWORD
- 401 INVALID_CREDENTIALS
- 422 VALIDATION_ERROR

## 5.2 Users

### GET /users

Auth: admin required

Success 200:

```json
[
  {
    "id": 1,
    "name": "admin",
    "email": "admin@example.com",
    "role": "admin"
  }
]
```

Errors:

- 403 INSUFFICIENT_PERMISSIONS

### PUT /users/{user_id}

Auth: admin required

Request body (all fields optional):

```json
{
  "username": "alice2",
  "email": "alice2@example.com",
  "role": "user"
}
```

Success 200:

```json
{
  "id": 2,
  "name": "alice2",
  "email": "alice2@example.com",
  "role": "user"
}
```

Errors:

- 400 SELF_ROLE_CHANGE_NOT_ALLOWED
- 400 INVALID_ROLE
- 400 PASSWORD_UPDATE_NOT_ALLOWED
- 404 USER_NOT_FOUND
- 403 INSUFFICIENT_PERMISSIONS

### POST /users/remediate-passwords

Auth: admin required

Query params:

- dry_run (boolean, default true)
- limit (integer, 1..500, default 100)

Success 200:

```json
{
  "processed_users": 1,
  "affected_users": [
    {
      "user_id": 5,
      "username": "legacy_user",
      "email": "legacy@example.com",
      "temporary_password": "TempPasswordGenerated"
    }
  ]
}
```

Notes:

- When dry_run=true, response reports impacted users without changing DB.
- When dry_run=false, invalid hashes are replaced with temporary hashed passwords.

Errors:

- 403 INSUFFICIENT_PERMISSIONS
- 422 VALIDATION_ERROR

### DELETE /users/{user_id}

Auth: admin required

Success 200:

```json
{
  "message": "User deleted successfully"
}
```

Errors:

- 400 SELF_DELETE_NOT_ALLOWED
- 404 USER_NOT_FOUND
- 403 INSUFFICIENT_PERMISSIONS

## 5.3 Tasks

### POST /tasks

Auth: authenticated user

Role behavior:

- admin: must provide either assigned_to or assigned_to_username.
- user: task is always assigned to current user, even if assignment fields are omitted.

Request body:

```json
{
  "title": "Build API docs",
  "description": "Write contract",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "assigned_to": 6,
  "sub_task_count": 2,
  "sub_tasks": [
    {
      "title": "Design request schema",
      "description": "Add nested subtask create fields",
      "status": "not complete",
      "priority": 90,
      "estimated_days": 0,
      "estimated_hours": 3,
      "actual_days": 0,
      "actual_hours": 2
    },
    {
      "title": "Implement router",
      "description": "Create task and subtasks atomically",
      "status": "not complete",
      "priority": 10,
      "estimated_days": 0,
      "estimated_hours": 5,
      "actual_days": 0,
      "actual_hours": 1
    }
  ]
}
```

Nested validation:

- sub_tasks is optional.
- sub_task_count is optional.
- If sub_task_count is provided, sub_tasks must also be provided.
- If both are provided, sub_task_count must equal len(sub_tasks).
- If sub_tasks is provided and not empty, sum of all sub_task.priority values must be exactly 100.

Success 200:

```json
{
  "id": 10,
  "title": "Build API docs",
  "description": "Write contract",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "status": "not complete",
  "estimated_days": 0,
  "estimated_hours": 8,
  "created_by": {
    "id": 1,
    "name": "admin"
  },
  "assigned_to": {
    "id": 6,
    "name": "divya"
  },
  "version": 1,
  "parent_task_id": null,
  "sub_tasks": [
    {
      "id": 101,
      "title": "Design request schema",
      "description": "Add nested subtask create fields",
      "status": "not complete",
      "priority": 90,
      "estimated_days": 0,
      "estimated_hours": 3,
      "actual_days": 0,
      "actual_hours": 2,
      "created_at": "2026-03-03T09:05:00",
      "task_id": 10,
      "created_by": {
        "id": 1,
        "name": "admin"
      }
    }
  ],
  "sub_tasks_created_count": 2
}
```

Errors:

- 404 ASSIGNED_USER_NOT_FOUND
- 400 INVALID_SUBTASK_PRIORITY_TOTAL
- 500 TRANSACTION_FAILED
- 422 VALIDATION_ERROR

### GET /my-tasks

Auth: authenticated user

Query params:

- page (int >= 1, default 1)
- page_size (int 1..100, default 10)
- search (string, optional)
- status (string, optional)

Success 200:

```json
{
  "items": [
    {
      "id": 10,
      "title": "Build API docs",
      "description": "Write contract",
      "start_date": "2026-03-03T09:00:00",
      "end_date": "2026-03-05T18:00:00",
      "status": "not complete",
      "estimated_days": 0,
      "estimated_hours": 8,
      "created_by": {
        "id": 1,
        "name": "admin"
      },
      "assigned_to": {
        "id": 6,
        "name": "divya"
      },
      "version": 1,
      "parent_task_id": null,
      "sub_tasks": []
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10,
  "total_pages": 1
}
```

### PUT /tasks/{task_id}/complete

Auth: authenticated user

Rules:

- Only assigned user can complete task.
- Admin does not bypass this check in current implementation.

Success 200:

```json
{
  "message": "Task marked complete"
}
```

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS

### GET /tasks

Auth: admin required

Query params:

- page (int >= 1, default 1)
- page_size (int 1..100, default 10)
- search (string, optional)
- status (string, optional)
- assigned_to (int, optional)

Success 200:

```json
{
  "items": [
    {
      "id": 10,
      "title": "Build API docs",
      "description": "Write contract",
      "start_date": "2026-03-03T09:00:00",
      "end_date": "2026-03-05T18:00:00",
      "status": "not complete",
      "estimated_days": 0,
      "estimated_hours": 8,
      "created_by": {
        "id": 1,
        "name": "admin"
      },
      "assigned_to": {
        "id": 6,
        "name": "divya"
      }
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10,
  "total_pages": 1
}
```

Errors:

- 403 INSUFFICIENT_PERMISSIONS

### GET /tasks/{task_id}

Auth: authenticated user

Rules:

- Assigned user and admin can access.

Success 200:

```json
{
  "id": 10,
  "title": "Build API docs",
  "description": "Write contract",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "status": "not complete",
  "estimated_days": 0,
  "estimated_hours": 8,
  "created_by": {
    "id": 1,
    "name": "admin"
  },
  "assigned_to": {
    "id": 6,
    "name": "divya"
  },
  "version": 1,
  "parent_task_id": null,
  "sub_tasks": [
    {
      "id": 101,
      "title": "Design request schema",
      "description": "Add nested subtask create fields",
      "status": "not complete",
      "priority": 90,
      "estimated_days": 0,
      "estimated_hours": 3,
      "actual_days": 0,
      "actual_hours": 2,
      "created_at": "2026-03-03T09:05:00",
      "task_id": 10,
      "created_by": {
        "id": 1,
        "name": "admin"
      }
    }
  ]
}
```

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS

### GET /tasks/{task_id}/progress

Auth: authenticated user

Rules:

- Assigned user and admin can access.

Success 200:

```json
{
  "task_id": 10,
  "total_subtasks": 2,
  "completed_subtasks": 1,
  "progress_percentage": 50.0,
  "is_completed": false
}
```

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS

### GET /tasks/{task_id}/timeline

Auth: authenticated user

Rules:

- Assigned user and admin can access.

Success 200:

```json
{
  "task_id": 10,
  "task_title": "Build API docs",
  "total_estimated_hours": 8.0,
  "total_actual_hours": 3.0,
  "total_expected_hours": 7.2,
  "bars": [
    {
      "key": "estimated",
      "label": "How much time it will take",
      "hours": 8.0,
      "percentage": 100.0
    },
    {
      "key": "actual",
      "label": "How much time user took",
      "hours": 3.0,
      "percentage": 37.5
    },
    {
      "key": "expected",
      "label": "How much time it should have taken",
      "hours": 7.2,
      "percentage": 90.0
    }
  ],
  "sub_tasks": [
    {
      "sub_task_id": 101,
      "title": "Design request schema",
      "status": "complete",
      "priority": 90,
      "estimated_hours": 3.0,
      "actual_hours": 2.0,
      "expected_hours": 7.2
    },
    {
      "sub_task_id": 102,
      "title": "Implement router",
      "status": "not complete",
      "priority": 10,
      "estimated_hours": 5.0,
      "actual_hours": 1.0,
      "expected_hours": 0.0
    }
  ]
}
```

Notes:

- expected bar uses priority-weighted share of total estimated hours.
- If total priority for the task is 0, timeline uses equal weights across subtasks.
- expected hours are counted only for completed subtasks.

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS

### PUT /tasks/{task_id}/subtasks/priorities

### POST /tasks/{task_id}/subtasks/priorities

Auth: authenticated user

Rules:

- Allowed for admin or user assigned to parent task.
- Payload must include every sub-task for the task exactly once.
- items[].priority values must sum to exactly 100.

Request body:

```json
{
  "items": [
    {
      "sub_task_id": 101,
      "priority": 90
    },
    {
      "sub_task_id": 102,
      "priority": 10
    }
  ]
}
```

Success 200:

```json
{
  "task_id": 10,
  "total_priority": 100,
  "items": [
    {
      "sub_task_id": 101,
      "priority": 90
    },
    {
      "sub_task_id": 102,
      "priority": 10
    }
  ]
}
```

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS
- 400 SUBTASKS_NOT_FOUND
- 400 EMPTY_PRIORITY_PAYLOAD
- 400 INCOMPLETE_PRIORITY_PAYLOAD
- 400 DUPLICATE_SUBTASK_IN_PAYLOAD
- 400 INVALID_SUBTASK_SET
- 400 INVALID_SUBTASK_PRIORITY_TOTAL

### PUT /tasks/{task_id}

Auth: admin required

Request body (all fields optional):

```json
{
  "title": "Updated title",
  "description": "Updated description",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-07T18:00:00",
  "status": "in progress",
  "assigned_to": 7,
  "assigned_to_username": "newassignee"
}
```

Notes:

- If assigned_to_username is provided in payload, it overrides assigned_to.
- If status change is requested on an already complete task, request fails.

Success 200:

TaskResponse shape (same as task object without sub_tasks).

Errors:

- 404 TASK_NOT_FOUND
- 404 ASSIGNED_USER_NOT_FOUND
- 400 TASK_ALREADY_COMPLETE
- 403 INSUFFICIENT_PERMISSIONS

### POST /tasks/{task_id}/revise

Auth: authenticated user

Rules:

- Original task must be complete.
- Allowed for assigned user or admin.
- Creates a new task version with:
  - version = previous version + 1
  - parent_task_id = previous task id
  - status = not complete
  - estimated_days = 0
  - estimated_hours = 0

Success 200:

TaskResponse shape.

Errors:

- 404 TASK_NOT_FOUND
- 400 TASK_NOT_COMPLETE
- 403 FORBIDDEN_TASK_ACCESS

### DELETE /tasks/{task_id}

Auth: admin required

Success 200:

```json
{
  "message": "Task deleted successfully"
}
```

Errors:

- 404 TASK_NOT_FOUND
- 403 INSUFFICIENT_PERMISSIONS

## 5.4 Subtasks

### POST /subtasks

Auth: authenticated user

Request body:

```json
{
  "title": "Design schema",
  "description": "Prepare fields",
  "status": "not complete",
  "priority": 100,
  "estimated_days": 0,
  "estimated_hours": 4,
  "actual_days": 0,
  "actual_hours": 2,
  "task_id": 10
}
```

Rules:

- task_id must exist.
- Allowed for admin or user assigned to parent task.
- After creation, priorities for all subtasks under task_id must sum to exactly 100.

Success 200:

SubTaskResponse shape.

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS
- 400 INVALID_SUBTASK_PRIORITY_TOTAL
- 422 VALIDATION_ERROR

### GET /subtasks

Auth: authenticated user

Query params:

- page (int >= 1, default 1)
- page_size (int 1..100, default 10)
- search (string, optional)
- status (string, optional)
- task_id (int, optional)

Visibility:

- admin sees all subtasks.
- user sees subtasks only for tasks assigned to them.

Success 200:

SubTask list pagination envelope.

### GET /subtasks/{sub_task_id}

Auth: authenticated user

Rules:

- subtask must exist.
- caller must have access to parent task (admin or assigned user).

Success 200:

SubTaskResponse shape.

Errors:

- 404 SUBTASK_NOT_FOUND
- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS

### PUT /subtasks/{sub_task_id}

Auth: authenticated user

Request body (all fields optional):

```json
{
  "title": "Refine schema",
  "description": "Add constraints",
  "status": "complete",
  "priority": 90,
  "estimated_days": 0,
  "estimated_hours": 5,
  "actual_days": 0,
  "actual_hours": 3,
  "task_id": 11
}
```

Rules:

- Completed subtasks cannot be reopened.
- New task_id, if provided, must exist.
- On update, parent task estimate totals are recalculated.
- After update/move, each affected task that still has subtasks must have priority total exactly 100.

Success 200:

SubTaskResponse shape.

Errors:

- 404 SUBTASK_NOT_FOUND
- 404 TASK_NOT_FOUND
- 400 SUBTASK_ALREADY_COMPLETE
- 400 INVALID_SUBTASK_PRIORITY_TOTAL
- 403 FORBIDDEN_TASK_ACCESS

### DELETE /subtasks/{sub_task_id}

Auth: authenticated user

Rules:

- caller must be admin or assigned user of parent task.
- Deletion is allowed if remaining subtasks are zero, or if remaining priorities still sum to exactly 100.

Success 200:

```json
{
  "message": "Sub task deleted successfully"
}
```

Errors:

- 404 SUBTASK_NOT_FOUND
- 404 TASK_NOT_FOUND
- 400 INVALID_SUBTASK_PRIORITY_TOTAL
- 403 FORBIDDEN_TASK_ACCESS

## 5.5 Activities

### POST /activities

Auth: admin required

Request body:

```json
{
  "title": "Code review",
  "description": "Review implementation",
  "date": "2026-03-04",
  "sub_task_id": 101
}
```

Rules:

- sub_task_id must exist.

Success 200:

ActivityResponse shape:

```json
{
  "id": 201,
  "title": "Code review",
  "description": "Review implementation",
  "date": "2026-03-04",
  "status": "not complete",
  "sub_task_id": 101,
  "created_by": {
    "id": 1,
    "name": "admin"
  }
}
```

Errors:

- 404 SUBTASK_NOT_FOUND
- 403 INSUFFICIENT_PERMISSIONS

### PUT /activities/{activity_id}

Auth: admin required

Request body (all fields optional):

```json
{
  "title": "Updated activity",
  "description": "Updated",
  "date": "2026-03-05",
  "status": "complete",
  "sub_task_id": 102
}
```

Rules:

- Completed activity cannot be reopened.
- status (if provided) must be one of: complete, not complete.
- sub_task_id (if provided) must exist.

Success 200:

ActivityResponse shape.

Errors:

- 404 ACTIVITY_NOT_FOUND
- 404 SUBTASK_NOT_FOUND
- 400 ACTIVITY_ALREADY_COMPLETE
- 400 INVALID_ACTIVITY_STATUS
- 403 INSUFFICIENT_PERMISSIONS

### DELETE /activities/{activity_id}

Auth: admin required

Success 200:

```json
{
  "message": "Activity deleted successfully"
}
```

Errors:

- 404 ACTIVITY_NOT_FOUND
- 403 INSUFFICIENT_PERMISSIONS

### GET /tasks/{task_id}/activities

Auth: authenticated user

Query params:

- page (int >= 1, default 1)
- page_size (int 1..100, default 10)
- search (string, optional)
- status (string, optional)
- sub_task_id (int, optional)

Rules:

- task_id must exist.
- allowed for admin or assigned user of task.

Success 200:

Activity list pagination envelope.

Errors:

- 404 TASK_NOT_FOUND
- 403 FORBIDDEN_TASK_ACCESS

## 5.6 Audit Logs

### GET /audit-logs

Auth: authenticated user

Query params:

- page (int >= 1, default 1)
- page_size (int 1..100, default 20)
- action (string, optional)
- entity_type (string, optional)
- entity_id (int, optional)
- user_id (int, optional; honored only for admin)
- search (string, optional)
- start_date (datetime, optional)
- end_date (datetime, optional)

Visibility:

- admin sees all logs (and can filter by user_id).
- user sees only own logs.

Success 200:

```json
{
  "items": [
    {
      "id": 500,
      "action": "CREATE",
      "entity_type": "task",
      "entity_id": 10,
      "message": "Task created",
      "details": {
        "title": "Build API docs"
      },
      "user_id": 1,
      "user": {
        "id": 1,
        "name": "admin"
      },
      "created_at": "2026-03-03T09:05:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

## 5.7 Dashboard

### GET /dashboard

Auth: authenticated user

Visibility:

- admin: aggregates over all tasks.
- user: aggregates over tasks assigned to current user.

Success 200:

```json
{
  "total_tasks": 10,
  "completed_tasks": 4,
  "in_progress_tasks": 3,
  "overdue_tasks": 2,
  "recent_tasks": [
    {
      "id": 10,
      "title": "Build API docs",
      "status": "not complete",
      "end_date": "2026-03-05T18:00:00",
      "assigned_to": {
        "id": 6,
        "name": "divya"
      }
    }
  ]
}
```

## 6. Enum and Field Constraints

### 6.1 Task Status

Allowed values:

- complete
- not complete
- in progress
- blocked

### 6.2 Subtask Status

Allowed values:

- complete
- not complete

### 6.3 Numeric Constraints

- task sub_task_count >= 0
- subtask priority >= 0 and <= 100
- subtask estimated_days >= 0
- subtask estimated_hours >= 0 and < 24
- subtask actual_days >= 0
- subtask actual_hours >= 0 and < 24

## 7. Audit Logging Behavior

The following actions create audit log records:

- Auth: LOGIN, PASSWORD_CHANGE, PASSWORD_MIGRATION
- Users: CREATE, UPDATE, DELETE, PASSWORD_REMEDIATION
- Tasks: CREATE, UPDATE, COMPLETE, REVISE, DELETE
- Subtasks: CREATE, UPDATE, DELETE
- Activities: CREATE, UPDATE, DELETE

## 8. Implementation Notes

- Some successful operation endpoints return simple message-only bodies.
- All API errors pass through the unified error handlers in app/core/errors.py.
- Request correlation id is attached for every request and returned in response header x-request-id.
