# QA Change Control - Review Changes

This package is based on the uploaded `rsd_qa_management` module. Existing technical field and method names containing `ab` have intentionally been retained; terminology renaming was deferred as requested.

## Updated files

- `models/qa_change_control.py`
  - Restricts Change Request creation fields.
  - Enforces stage-specific QA field write permissions.
  - Blocks direct state writes for every user, including System Administrators.
  - Requires exactly one valid pending approval-history record before approval/refusal.
  - Validates approval-history creation and locks document parent/uploader fields.
  - Keeps completion metadata updates inside the validated completion action.
- `models/qa_change_control_task.py`
  - Only the assigned employee can start or submit tasks.
  - QA can request rework, but cannot submit on behalf of an employee.
  - Blocks direct task state/submission-date changes and parent Change Request reassignment.
  - Prevents editing submitted tasks until QA requests rework.
  - Requires assigned employee to be linked to an internal Odoo user.
- `models/qa_change_control_wizard.py`
  - Validates that rejection/refusal reasons are not blank or whitespace-only.
  - Validates that the referenced Change Request still exists.
- `views/qa_change_control_views.xml`
  - Keeps Kanban stage dragging disabled for administrators too.
  - Shows Start/Submit Task buttons only to the assigned employee.
- `README.md`
  - Corrects descriptions of the reminder and Kanban behavior.

## Validation performed

- Python source parsed successfully.
- XML files parsed successfully.
- This is static validation only. The package has not been installed or functionally tested against the user's Odoo database.

## Installation caution

Back up the current module folder and database before replacing files or upgrading the module. Test the package on a development/staging database first.

- `security/security.xml` and `security/ir.model.access.csv`
  - Restricts the full Change Control menu and QA dashboard to QA.
  - Keeps requester, assigned-task and current-Approver access through separate self-service menus and record rules.
  - Makes QA review documents QA-only.
  - Removes task creation permission from ordinary internal users.
- `views/qa_menus.xml` and `views/qa_change_control_views.xml`
  - Adds My Change Requests, My Evaluation Tasks and My Approvals entry points.
  - Renames user-facing Approver terminology without changing technical identifiers.
