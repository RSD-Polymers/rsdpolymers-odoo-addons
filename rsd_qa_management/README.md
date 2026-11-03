# Quality Assurance - Odoo 18

## Implemented in version 18.0.1.1.0

### Change Control
- Change Request model: `qa.change.control`
- Evaluation Task model: `qa.change.control.task` (separate from `project.task`)
- Review document model: `qa.change.control.document`
- Approval history log and rejection / AB refusal wizards
- Draft -> Open -> Registered -> Evaluation -> Data Review -> Awaiting AB Approval -> Closing Report -> Completed workflow
- QA rejection from Open closes the CR as Rejected and requires a reason
- First submitted evaluation task automatically moves the CR to Data Review and notifies QA
- Remaining evaluation tasks may still be submitted while the CR is in Data Review
- QA can send for AB approval only after all evaluation tasks are submitted
- AB is a selected internal Odoo user; only the assigned AB user can approve/refuse
- AB refusal returns the CR to Evaluation and requires a reason
- QA-only review documents and closing report
- Post-implementation report, implementation date and comments required for final completion
- Mail chatter and activities for workflow notifications
- Assigned employee deadline activity and daily QA reminder one day before task due date

### Views and dashboard
- Change Control List, Kanban, Form and Search views
- Kanban stage dragging is disabled for all users, including administrators
- Server-side state-write protection blocks direct stage changes for all users, including administrators, even through RPC/import
- Dashboard KPIs are calculated from live Change Control records
- Pending and completed KPI cards open filtered record lists
- Stage cards open records filtered by stage

### Security
- QA Officer and QA Manager groups
- Employees can create and view their own Change Requests
- Assigned task employees can access their assigned tasks and submit task updates
- AB approver can access the Change Request assigned to them and use approval actions
- Workflow stage changes are protected in Python; direct state writes are blocked for all users
- QA can manage all Change Control records and tasks

## Installation / Upgrade
1. Copy `rsd_qa_management` into a configured custom addons directory.
2. Ensure Odoo service user can read the module files.
3. Restart Odoo and upgrade the module from Apps or with `-u rsd_qa_management`.
4. Assign QA Officer / QA Manager groups to the relevant users.
5. Ensure employees and their Odoo users are linked in HR.

## Important configuration
- Assign an AB Approver on the Change Request during Data Review before sending for approval.
- Assigned employees must have an internal Odoo user linked to their HR employee record.
- A daily scheduled action is configured to remind assigned employees and QA users one day before task deadlines.

## Remaining planned enhancements
- Additional reminder escalation rules and reminder reporting (if required).
- Configurable multi-level approval if required.
- Additional dashboard charts and date-range filters.
