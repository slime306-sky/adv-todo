# API Contract

> Formal machine-readable spec: see `openapi_contract.yaml`.

This document describes the HTTP API exposed by this FastAPI project. The app mounts the routers directly, so the paths below are the real request paths served by the application.

## Base Rules

- Base URL: the API is served by the FastAPI app in `app/main.py`.
- Authentication: protected routes require a Bearer token in the `Authorization` header.
- Roles: the API uses two roles, `admin` and `user`.
- Pagination: list endpoints return `items`, `total`, `page`, `page_size`, and `total_pages`.
- Dates and times: datetime values are returned in ISO 8601 format. `Activity.date` is a date value.
- Error format: all API errors use a consistent JSON payload with `message`, `code`, `dev_message`, `request_id`, `path`, and optional `details`.

## Common Error Shape

```json
{
  "message": "Not authorized",
  "code": "FORBIDDEN_TASK_ACCESS",
  "dev_message": "Not authorized",
  "request_id": "...",
  "path": "/tasks/1"
}
```

Validation failures return `422` with `code: VALIDATION_ERROR` and a `details` array from Pydantic.

## Shared Data Shapes

### User reference

```json
{
  "id": 1,
  "name": "alice"
}
```

### Department reference

```json
{
  "id": 1,
  "name": "Engineering"
}
```

### Task status values

- `complete`
- `not complete`
- `in progress`
- `blocked`

### Sub-task status values

- `complete`
- `not complete`

### Sub-task update request status values

- `pending`
- `approved`
- `rejected`

### Activity status values

- `complete`
- `not complete`

## Auth

### POST /register

Admin-only user creation.

Request body:

```json
{
  "username": "new_user",
  "email": "new_user@example.com",
  "password": "secret123",
  "role": "user"
}
```

Response:

```json
{
  "message": "User created"
}
```

### POST /login

Public login endpoint.

Request body:

```json
{
  "username": "alice",
  "password": "secret123"
}
```

Response:

```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "username": "alice",
  "role": "admin",
  "user": {
    "id": 1,
    "name": "alice"
  }
}
```

### POST /change-password

Authenticated users change their own password.

Request body:

```json
{
  "current_password": "old-secret",
  "new_password": "new-secret"
}
```

Response:

```json
{
  "message": "Password changed successfully"
}
```

## Users

### GET /users

Admin-only. Returns all users.

Response item shape:

```json
{
  "id": 1,
  "name": "alice",
  "email": "alice@example.com",
  "role": "admin",
  "departments": [
    {"id": 1, "name": "Engineering"}
  ]
}
```

### PUT /users/{user_id}

Admin-only. Updates username, email, or role.

Request body:

```json
{
  "username": "alice2",
  "email": "alice2@example.com",
  "role": "user"
}
```

### DELETE /users/{user_id}

Admin-only. Deletes a user after re-pointing dependent rows.

Response:

```json
{
  "message": "User deleted successfully"
}
```

### POST /users/remediate-passwords

Admin-only. Rotates users with invalid password hashes.

Query params:

- `dry_run` default `true`
- `limit` default `100`

Response:

```json
{
  "processed_users": 2,
  "affected_users": [
    {
      "user_id": 4,
      "username": "legacy_user",
      "email": "legacy@example.com",
      "temporary_password": "AbC123..."
    }
  ]
}
```

## Departments

### POST /departments

Admin-only. Creates a new department.

Request body:

```json
{
  "name": "Engineering"
}
```

Response:

```json
{
  "id": 1,
  "name": "Engineering"
}
```

### GET /departments

Authenticated users can list departments.

### PUT /users/{user_id}/departments

Admin-only. Replaces the user’s department assignments.

Request body:

```json
{
  "department_ids": [1, 2, 3]
}
```

Response:

```json
{
  "message": "User departments updated",
  "department_ids": [1, 2, 3]
}
```

## Tasks

### POST /tasks

Creates a task. Assignment now lives on sub-tasks, so task creation only needs the task title, description, and optional nested sub-tasks.

Request body:

```json
{
  "title": "Build API",
  "description": "Implement backend endpoints",
  "sub_tasks": [
    {
      "title": "Design schema",
      "description": "Draft DB tables",
      "status": "not complete",
      "priority": 50,
      "estimated_days": 1,
      "estimated_hours": 0,
      "actual_days": 0,
      "actual_hours": 0,
      "assigned_to": 2
    }
  ],
  "sub_task_count": 1
}
```

Important rules:

- If `sub_task_count` is provided, it must match the number of `sub_tasks`.
- When nested `sub_tasks` are provided, their priorities must sum to exactly `100`.

Response:

```json
{
  "id": 1,
  "title": "Build API",
  "description": "Implement backend endpoints",
  "status": "not complete",
  "estimated_days": 1,
  "estimated_hours": 0,
  "created_by": {"id": 1, "name": "alice"},
  "version": "1.0.0",
  "parent_task_id": null,
  "sub_tasks": [],
  "sub_tasks_created_count": 1
}
```

### GET /my-tasks

Returns the current user’s assigned tasks.

In the current model, this means tasks that you created or tasks that contain at least one sub-task assigned to you.

Query params:

- `page` default `1`
- `page_size` default `10`
- `search` optional
- `status` optional

### PUT /tasks/{task_id}/complete

Marks the current user’s assigned task as complete.

Response:

```json
{
  "message": "Task marked complete"
}
```

### GET /tasks

Admin-only task listing.

Query params:

- `page` default `1`
- `page_size` default `10`
- `search` optional
- `status` optional

### GET /tasks/{task_id}

Returns a task with nested sub-tasks.

### GET /tasks/{task_id}/progress

Returns progress metrics for a task.

Response:

```json
{
  "task_id": 1,
  "total_subtasks": 4,
  "completed_subtasks": 2,
  "progress_percentage": 50,
  "is_completed": false
}
```

### GET /tasks/{task_id}/timeline

Returns estimated, actual, and expected time bars plus per-sub-task timeline data.

### PUT /tasks/{task_id}/subtasks/priorities
### POST /tasks/{task_id}/subtasks/priorities

Reorders or reprioritizes all sub-tasks on a task in one request.

Request body:

```json
{
  "items": [
    {"sub_task_id": 1, "priority": 60},
    {"sub_task_id": 2, "priority": 40}
  ]
}
```

Rules:

- The payload must include every sub-task exactly once.
- Priorities must sum to exactly `100`.

### PUT /tasks/{task_id}

Authenticated task update.

Admins update the task immediately. Non-admin users create a pending task update request instead.

Request body:

```json
{
  "title": "Revised title",
  "description": "Updated description",
  "status": "in progress"
}
```

If the task is already complete, a status change that reopens it is still rejected.

### GET /task-update-requests/my

Returns the current user’s task update requests.

### GET /task-update-requests

Admin-only list of task update requests.

### PUT /task-update-requests/{request_id}/approve

Admin-only. Approves a pending task update request and applies the change.

### PUT /task-update-requests/{request_id}/reject

Admin-only. Rejects a pending task update request.

### POST /tasks/{task_id}/revise

Admin-only. Creates a new version of a completed task.

Request body:

```json
{
  "bump_type": "patch"
}
```

Allowed values: `major`, `minor`, `patch`.

### DELETE /tasks/{task_id}

Admin-only. Deletes a task.

## Sub-tasks

### POST /subtasks

Creates a sub-task under a task. The user must be allowed to manage the task.

Request body:

```json
{
  "title": "Draft schema",
  "description": "Create the initial schema",
  "status": "not complete",
  "priority": 100,
  "estimated_days": 1,
  "estimated_hours": 4,
  "actual_days": 0,
  "actual_hours": 0,
  "task_id": 1
}
```

Response:

```json
{
  "id": 1,
  "title": "Draft schema",
  "description": "Create the initial schema",
  "status": "not complete",
  "priority": 100,
  "estimated_days": 1,
  "estimated_hours": 4,
  "actual_days": 0,
  "actual_hours": 0,
  "created_at": "2026-04-05T09:00:00Z",
  "completed_at": null,
  "task_id": 1,
  "created_by": {"id": 1, "name": "alice"},
  "assigned_to": {"id": 2, "name": "bob"}
}
```

### GET /subtasks

Lists sub-tasks. Non-admin users only see sub-tasks for tasks assigned to them.

In the new model, that means sub-tasks assigned to the current user or sub-tasks that belong to tasks they created.

Query params:

- `page` default `1`
- `page_size` default `10`
- `search` optional
- `status` optional
- `task_id` optional

### GET /subtasks/{sub_task_id}

Returns one sub-task if the user can manage its parent task.

### PUT /subtasks/{sub_task_id}

Updates a sub-task.

Behavior:

- Admins update the sub-task immediately.
- Non-admins create a pending approval request instead of applying the update.
- Completed sub-tasks cannot be reopened.
- Reassigned or re-prioritized updates must still keep task-level priority totals at exactly `100`.

### GET /subtask-update-requests/my

Returns the current user’s pending and reviewed update requests.

### GET /subtask-update-requests

Admin-only list of update requests.

Query params:

- `status` optional
- `page` default `1`
- `page_size` default `10`

### PUT /subtask-update-requests/{request_id}/approve

Admin-only. Applies the requested sub-task changes and marks the request approved.

Request body:

```json
{
  "comment": "Approved"
}
```

### PUT /subtask-update-requests/{request_id}/reject

Admin-only. Marks the request rejected.

Request body:

```json
{
  "comment": "Needs more detail"
}
```

### DELETE /subtasks/{sub_task_id}

Deletes a sub-task if the user can manage the parent task.

Response:

```json
{
  "message": "Sub task deleted successfully"
}
```

## Activities

### POST /activities

Admin-only. Creates an activity linked to a sub-task.

Request body:

```json
{
  "title": "Review schema",
  "description": "Inspect the new table structure",
  "date": "2026-04-05",
  "sub_task_id": 1
}
```

### PUT /activities/{activity_id}

Admin-only. Updates an activity.

### DELETE /activities/{activity_id}

Admin-only. Deletes an activity.

### GET /tasks/{task_id}/activities

Returns activities for a task. The caller must own the task or be an admin.

Query params:

- `page` default `1`
- `page_size` default `10`
- `search` optional
- `status` optional
- `sub_task_id` optional

## Dashboard

### GET /dashboard

Returns summary counts and the three most recent tasks visible to the caller.

Response shape:

```json
{
  "total_tasks": 12,
  "completed_tasks": 4,
  "in_progress_tasks": 3,
  "pending_tasks": 5,
  "recent_tasks": [
    {
      "id": 12,
      "title": "Build API",
      "status": "in progress",
      "created_by": {"id": 1, "name": "alice"}
    }
  ]
}
```

## Audit Logs

### GET /audit-logs

Returns audit entries. Non-admin users only see their own logs.

Query params:

- `page` default `1`
- `page_size` default `20`
- `action` optional
- `entity_type` optional
- `entity_id` optional
- `user_id` admin-only filter
- `search` optional
- `start_date` optional
- `end_date` optional

Response item shape:

```json
{
  "id": 1,
  "action": "CREATE",
  "entity_type": "task",
  "entity_id": 1,
  "message": "Task created",
  "details": {"title": "Build API"},
  "user_id": 1,
  "user": {"id": 1, "name": "alice"},
  "created_at": "2026-04-05T09:00:00Z"
}
```

## Notes

- `created_by` and similar user references are serialized as `{ id, name }`.
- Some delete and update routes return only a message instead of a full entity.
- `Task.version` is exposed as a string like `1.0.0`, backed by major/minor/patch fields.
- A revised task creates a new task row with `parent_task_id` pointing at the original task.