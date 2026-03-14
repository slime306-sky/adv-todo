# To-Do App API Contract

Version: 1.1 (current implementation)

This contract documents the API behavior as implemented in the current FastAPI codebase.

## Base Information

- Framework: FastAPI
- Base URL (local): `http://127.0.0.1:8000`
- OpenAPI JSON: `GET /openapi.json`
- Interactive docs: `GET /docs`
- Default success code for most routes: `200 OK`

## Authentication and Authorization

### Auth Type

- JWT Bearer token
- OAuth2 password flow with token URL: `/login`

### Login Input Format

- `POST /login` accepts `application/x-www-form-urlencoded`
- Required form fields:
  - `username`
  - `password`

### Token Usage

Send access token in header:

```http
Authorization: Bearer <access_token>
```

### Role Model

- `admin`: can access admin-only routes.
- `user`: can access user-scoped routes.

Admin-only routes use role guard and return:

- `403` with structured body (see Error Contract below)

## Error Contract

### Unified Error Shape

All API errors now follow:

```json
{
  "message": "Human-readable message",
  "code": "MACHINE_READABLE_CODE",
  "dev_message": "Developer-focused detail",
  "request_id": "uuid-or-x-request-id",
  "path": "/requested/path"
}
```

Fields:
- `message`: user/frontend friendly summary.
- `code`: stable machine-readable error code (`NOT_FOUND`, `VALIDATION_ERROR`, etc.).
- `dev_message`: debugging context for developers.
- `request_id`: correlation id (uses incoming `x-request-id` header if present, otherwise generated).
- `path`: request path.

### Custom Error Codes (current)

- Auth/Security:
  - `USERNAME_ALREADY_EXISTS`
  - `INVALID_CREDENTIALS`
  - `INVALID_TOKEN`
  - `INSUFFICIENT_PERMISSIONS`
- Users:
  - `USER_NOT_FOUND`
  - `SELF_ROLE_CHANGE_NOT_ALLOWED`
  - `INVALID_ROLE`
  - `SELF_DELETE_NOT_ALLOWED`
- Tasks:
  - `TASK_NOT_FOUND`
  - `ASSIGNED_USER_NOT_FOUND`
  - `FORBIDDEN_TASK_ACCESS`
- Activities:
  - `ACTIVITY_NOT_FOUND`
  - `INVALID_ACTIVITY_STATUS`
- Sub-tasks:
  - `SUBTASK_NOT_FOUND`
  - `SUBTASK_ACTIVITY_TASK_MISMATCH`

### Validation Errors

Validation failures return `422 Unprocessable Entity` with the same unified shape plus `details`:

```json
{
  "message": "Validation failed",
  "code": "VALIDATION_ERROR",
  "dev_message": "One or more request fields are invalid",
  "request_id": "uuid-or-x-request-id",
  "path": "/requested/path",
  "details": [
    {
      "loc": ["body", "field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

## Endpoints

---

## 0) Audit Logs

### 0.1 Get Audit Logs

- Method: `GET`
- Path: `/audit-logs`
- Auth required: Yes (authenticated user)
- Query params:
  - `page` (default `1`)
  - `page_size` (default `20`, max `100`)
  - `action` (optional)
  - `entity_type` (optional)
  - `entity_id` (optional)
  - `user_id` (optional, admin only)
  - `search` (optional)
  - `start_date` (optional, ISO datetime)
  - `end_date` (optional, ISO datetime)

Success response (`200 OK`):

```json
{
  "items": [
    {
      "id": 101,
      "action": "CREATE",
      "entity_type": "task",
      "entity_id": 10,
      "message": "Task created",
      "details": {
        "title": "Build API contract",
        "assigned_to": 2
      },
      "user_id": 1,
      "created_at": "2026-03-06T13:20:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

Behavior:
- Admin can view all audit logs.
- Non-admin users only see logs where `user_id` matches their account.

---

## 1) Auth

### 1.1 Register User

- Method: `POST`
- Path: `/register`
- Auth required: No
- Request body (`application/json`):

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "secret123",
  "role": "user"
}
```

Notes:
- `role` defaults to `"user"` if omitted.

Success response (`200 OK`):

```json
{
  "message": "User created"
}
```

Error responses:
- `400` `{ "detail": "Username already exists" }`
- `422` validation error

### 1.2 Login

- Method: `POST`
- Path: `/login`
- Auth required: No
- Request body (`application/x-www-form-urlencoded`):

```txt
username=alice&password=secret123
```

Success response (`200 OK`):

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

Error responses:
- `401` `{ "detail": "Invalid credentials" }`
- `422` validation error

---

## 2) Users (Admin)

### 2.1 Get All Users

- Method: `GET`
- Path: `/users`
- Auth required: Yes (admin)

Success response (`200 OK`):

```json
[
  {
    "username": "alice",
    "email": "alice@example.com",
    "role": "user"
  },
  {
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin"
  }
]
```

Error responses:
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`

### 2.2 Update User

- Method: `PUT`
- Path: `/users/{user_id}`
- Auth required: Yes (admin)
- Path params:
  - `user_id` (integer)
- Request body (`application/json`) all fields optional:

```json
{
  "username": "alice_new",
  "email": "alice_new@example.com",
  "role": "user"
}
```

Success response (`200 OK`):

```json
{
  "username": "alice_new",
  "email": "alice_new@example.com",
  "role": "user"
}
```

Error responses:
- `400` `{ "detail": "Admin cannot change own role" }`
- `400` `{ "detail": "Invalid role" }`
- `404` `{ "detail": "User not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`
- `422` validation error

### 2.3 Delete User

- Method: `DELETE`
- Path: `/users/{user_id}`
- Auth required: Yes (admin)
- Path params:
  - `user_id` (integer)

Success response (`200 OK`):

```json
{
  "message": "User deleted successfully"
}
```

Error responses:
- `400` `{ "detail": "Admin cannot delete themselves" }`
- `404` `{ "detail": "User not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`

---

## 3) Tasks

### 3.1 Create Task (Admin)

- Method: `POST`
- Path: `/tasks`
- Auth required: Yes (admin)
- Request body (`application/json`):

```json
{
  "title": "Build API docs",
  "description": "Write contract",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "assigned_to": 2
}
```

Success response (`200 OK`):

```json
{
  "id": 10,
  "title": "Build API docs",
  "description": "Write contract",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "status": "not complete",
  "created_by": 1,
  "assigned_to": 2
}
```

Error responses:
- `404` `{ "detail": "Assigned user not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`
- `422` validation error

### 3.2 Get My Tasks

- Method: `GET`
- Path: `/my-tasks`
- Auth required: Yes (authenticated user)

Success response (`200 OK`):

```json
[
  {
    "id": 10,
    "title": "Build API docs",
    "description": "Write contract",
    "start_date": "2026-03-03T09:00:00",
    "end_date": "2026-03-05T18:00:00",
    "status": "not complete",
    "created_by": 1,
    "assigned_to": 2
  }
]
```

Error responses:
- `401` invalid/missing token

### 3.3 Mark Task Complete

- Method: `PUT`
- Path: `/tasks/{task_id}/complete`
- Auth required: Yes (task assignee)
- Path params:
  - `task_id` (integer)

Success response (`200 OK`):

```json
{
  "message": "Task marked complete"
}
```

Error responses:
- `404` `{ "detail": "Task not found" }`
- `403` `{ "detail": "Not authorized" }`
- `401` invalid/missing token

### 3.4 Get All Tasks (Admin)

- Method: `GET`
- Path: `/tasks`
- Auth required: Yes (admin)

Success response (`200 OK`):

```json
[
  {
    "id": 10,
    "title": "Build API docs",
    "description": "Write contract",
    "status": "not complete",
    "creator_username": "admin",
    "assignee_username": "alice"
  }
]
```

Error responses:
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`

### 3.5 Update Task (Admin)

- Method: `PUT`
- Path: `/tasks/{task_id}`
- Auth required: Yes (admin)
- Path params:
  - `task_id` (integer)
- Request body (`application/json`) all fields optional:

```json
{
  "title": "Build API contract",
  "description": "Finalize docs",
  "start_date": "2026-03-03T10:00:00",
  "end_date": "2026-03-06T18:00:00",
  "status": "complete",
  "assigned_to": 2
}
```

Success response (`200 OK`):

```json
{
  "id": 10,
  "title": "Build API contract",
  "description": "Finalize docs",
  "start_date": "2026-03-03T10:00:00",
  "end_date": "2026-03-06T18:00:00",
  "status": "complete",
  "created_by": 1,
  "assigned_to": 2
}
```

Error responses:
- `404` `{ "detail": "Task not found" }`
- `404` `{ "detail": "Assigned user not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`
- `422` validation error

### 3.6 Delete Task (Admin)

- Method: `DELETE`
- Path: `/tasks/{task_id}`
- Auth required: Yes (admin)
- Path params:
  - `task_id` (integer)

Success response (`200 OK`):

```json
{
  "message": "Task deleted successfully"
}
```

Error responses:
- `404` `{ "detail": "Task not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`

---

## 4) Activities

### 4.1 Create Activity (Admin)

- Method: `POST`
- Path: `/activities`
- Auth required: Yes (admin)
- Request body (`application/json`):

```json
{
  "title": "Design endpoints",
  "description": "Map all routes",
  "date": "2026-03-03",
  "sub_task_id": 3
}
```

Success response (`200 OK`):

```json
{
  "id": 5,
  "title": "Design endpoints",
  "description": "Map all routes",
  "date": "2026-03-03",
  "status": "not complete",
  "sub_task_id": 3,
  "created_by": 1
}
```

Error responses:
- `404` `{ "detail": "Sub task not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`
- `422` validation error

### 4.2 Update Activity (Admin)

- Method: `PUT`
- Path: `/activities/{activity_id}`
- Auth required: Yes (admin)
- Path params:
  - `activity_id` (integer)
- Request body (`application/json`) all fields optional:

```json
{
  "title": "Design endpoint contracts",
  "description": "Add examples",
  "date": "2026-03-04",
  "status": "complete",
  "sub_task_id": 3
}
```

Success response (`200 OK`):

```json
{
  "id": 5,
  "title": "Design endpoint contracts",
  "description": "Add examples",
  "date": "2026-03-04",
  "status": "complete",
  "sub_task_id": 3,
  "created_by": 1
}
```

Error responses:
- `400` `{ "detail": "Invalid status" }` when status is not `"complete"` or `"not complete"`
- `404` `{ "detail": "Activity not found" }`
- `404` `{ "detail": "Sub task not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`
- `422` validation error

### 4.3 Delete Activity (Admin)

- Method: `DELETE`
- Path: `/activities/{activity_id}`
- Auth required: Yes (admin)
- Path params:
  - `activity_id` (integer)

Success response (`200 OK`):

```json
{
  "message": "Activity deleted successfully"
}
```

Error responses:
- `404` `{ "detail": "Activity not found" }`
- `401` invalid/missing token
- `403` `{ "detail": "Not enough permissions" }`

### 4.4 Get Activities for Task

- Method: `GET`
- Path: `/tasks/{task_id}/activities`
- Auth required: Yes (task assignee or admin)
- Path params:
  - `task_id` (integer)

Success response (`200 OK`):

```json
[
  {
    "id": 5,
    "title": "Design endpoints",
    "description": "Map all routes",
    "date": "2026-03-03",
    "status": "not complete",
    "sub_task_id": 3,
    "created_by": 1
  }
]
```

Error responses:
- `404` `{ "detail": "Task not found" }`
- `403` `{ "detail": "Not authorized" }`
- `401` invalid/missing token

Implementation note:
- Activities are linked through sub-tasks (`task -> sub-task -> activity`).

---

## 5) Sub Tasks

### 5.1 Create Sub Task

- Method: `POST`
- Path: `/subtasks`
- Auth required: Yes (admin or task assignee)
- Request body (`application/json`):

```json
{
  "title": "Draft serializer",
  "description": "Add pydantic schema",
  "status": "not complete",
  "estimated_days": 1,
  "estimated_hours": 4,
  "task_id": 10
}
```

Success response (`200 OK`):

```json
{
  "id": 3,
  "title": "Draft serializer",
  "description": "Add pydantic schema",
  "status": "not complete",
  "estimated_days": 1,
  "estimated_hours": 4,
  "created_at": "2026-03-06T10:15:00",
  "task_id": 10,
  "created_by": 2
}
```

Error responses:
- `404` `{ "detail": "Task not found" }`
- `403` `{ "detail": "Not authorized" }`
- `401` invalid/missing token
- `422` validation error (includes invalid status)

### 5.2 Get Sub Tasks

- Method: `GET`
- Path: `/subtasks`
- Auth required: Yes (authenticated user)

Success response (`200 OK`):

```json
[
  {
    "id": 3,
    "title": "Draft serializer",
    "description": "Add pydantic schema",
    "status": "not complete",
    "estimated_days": 1,
    "estimated_hours": 4,
    "created_at": "2026-03-06T10:15:00",
    "task_id": 10,
    "created_by": 2
  }
]
```

Behavior:
- Admin receives all sub tasks.
- User receives only sub tasks where parent task is assigned to them.

Error responses:
- `401` invalid/missing token

### 5.3 Get Sub Task By Id

- Method: `GET`
- Path: `/subtasks/{sub_task_id}`
- Auth required: Yes (admin or task assignee)

Success response (`200 OK`):

```json
{
  "id": 3,
  "title": "Draft serializer",
  "description": "Add pydantic schema",
  "status": "not complete",
  "estimated_days": 1,
  "estimated_hours": 4,
  "created_at": "2026-03-06T10:15:00",
  "task_id": 10,
  "created_by": 2
}
```

Error responses:
- `404` `{ "detail": "Sub task not found" }`
- `404` `{ "detail": "Task not found" }`
- `403` `{ "detail": "Not authorized" }`
- `401` invalid/missing token

### 5.4 Update Sub Task

- Method: `PUT`
- Path: `/subtasks/{sub_task_id}`
- Auth required: Yes (admin or task assignee)
- Request body (`application/json`) all fields optional:

```json
{
  "title": "Draft schema + validation",
  "description": "Finalize status enum",
  "status": "complete",
  "estimated_days": 0,
  "estimated_hours": 6,
  "task_id": 10
}
```

Success response (`200 OK`):

```json
{
  "id": 3,
  "title": "Draft schema + validation",
  "description": "Finalize status enum",
  "status": "complete",
  "estimated_days": 0,
  "estimated_hours": 6,
  "created_at": "2026-03-06T10:15:00",
  "task_id": 10,
  "created_by": 2
}
```

Error responses:
- `404` `{ "detail": "Sub task not found" }`
- `404` `{ "detail": "Task not found" }`
- `403` `{ "detail": "Not authorized" }`
- `401` invalid/missing token
- `422` validation error (includes invalid status)

### 5.5 Delete Sub Task

- Method: `DELETE`
- Path: `/subtasks/{sub_task_id}`
- Auth required: Yes (admin or task assignee)

Success response (`200 OK`):

```json
{
  "message": "Sub task deleted successfully"
}
```

Error responses:
- `404` `{ "detail": "Sub task not found" }`
- `404` `{ "detail": "Task not found" }`
- `403` `{ "detail": "Not authorized" }`
- `401` invalid/missing token

---

## Schema Reference

## Auth Schema

### Token

```json
{
  "access_token": "string",
  "token_type": "string"
}
```

## User Schemas

### UserCreate

```json
{
  "username": "string",
  "email": "string",
  "password": "string",
  "role": "user"
}
```

### UserResponse

```json
{
  "username": "string",
  "email": "string",
  "role": "string"
}
```

### UserUpdate (all optional)

```json
{
  "username": "string",
  "email": "string",
  "role": "string"
}
```

## Task Schemas

### TaskCreate

```json
{
  "title": "string",
  "description": "string",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "assigned_to": 2
}
```

### TaskUpdate (all optional)

```json
{
  "title": "string",
  "description": "string",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "status": "complete",
  "assigned_to": 2
}
```

### TaskResponse

```json
{
  "id": 10,
  "title": "string",
  "description": "string",
  "start_date": "2026-03-03T09:00:00",
  "end_date": "2026-03-05T18:00:00",
  "status": "not complete",
  "estimated_days": 2,
  "estimated_hours": 3,
  "created_by": 1,
  "assigned_to": 2
}
```

### TaskAdminResponse

```json
{
  "id": 10,
  "title": "string",
  "description": "string",
  "status": "not complete",
  "estimated_days": 2,
  "estimated_hours": 3,
  "creator_username": "admin",
  "assignee_username": "alice"
}
```

## Activity Schemas

### ActivityCreate

```json
{
  "title": "string",
  "description": "string",
  "date": "2026-03-03",
  "sub_task_id": 3
}
```

### ActivityUpdate (all optional)

```json
{
  "title": "string",
  "description": "string",
  "date": "2026-03-04",
  "status": "complete",
  "sub_task_id": 3
}
```

### ActivityResponse

```json
{
  "id": 5,
  "title": "string",
  "description": "string",
  "date": "2026-03-04",
  "status": "not complete",
  "sub_task_id": 3,
  "created_by": 1
}
```

## Sub Task Schemas

### SubTaskCreate

```json
{
  "title": "string",
  "description": "string",
  "status": "not complete",
  "estimated_days": 1,
  "estimated_hours": 4,
  "task_id": 10
}
```

### SubTaskUpdate (all optional)

```json
{
  "title": "string",
  "description": "string",
  "status": "complete",
  "estimated_days": 0,
  "estimated_hours": 6,
  "task_id": 10
}
```

### SubTaskResponse

```json
{
  "id": 3,
  "title": "string",
  "description": "string",
  "status": "not complete",
  "estimated_days": 1,
  "estimated_hours": 4,
  "created_at": "2026-03-06T10:15:00",
  "task_id": 10,
  "created_by": 2
}
```

---

## Implementation-Accurate Constraints

- Task status values used in code include: `"complete"`, `"not complete"`.
- Task estimated time is recalculated from all linked sub-tasks as `estimated_days` + `estimated_hours`.
- Activity update explicitly validates status to only: `"complete"` or `"not complete"`.
- Sub-task status is constrained by schema enum to: `"complete"` or `"not complete"`.
- Sub-task `estimated_hours` is constrained to `0-23`, and `estimated_days` must be `>= 0`.
- Login uses form data, not JSON.
- Create/delete endpoints currently return `200`, not `201/204`.
