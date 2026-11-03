# QA Change Control - Current Revision Notes

This revision applies the agreed QA Officer / QA Manager permission structure.

## Role permissions
- QA Officer: full operational and review access, including registration, evaluation task management, Data Review, rework requests, documents, and closing. Cannot approve or refuse.
- QA Manager: inherits QA Officer permissions and can approve or refuse Change Requests.
- Other internal users: can create and submit their own Change Requests and work only on tasks assigned to them.
- System Administrator: retains system/workflow administration rights but cannot approve or refuse unless also assigned to QA Manager.

## Approval behavior
- No separate Approver group or per-request approver selection is used.
- QA Officer sends a completed Data Review to the QA Manager group.
- All QA Managers can see the Pending Approvals queue.
- The first QA Manager to approve or refuse records the decision-maker, date, and comment. A database row lock serializes decisions so a second manager cannot decide the same pending request.
- Refusal requires a reason and returns the request to Evaluation.

## Evaluation task entry
- QA Officer creates tasks inline in the Change Request form during Evaluation.
- Task creation remains protected in Python and is rejected outside Evaluation.
- Assigned employees alone can start and submit their tasks. QA cannot submit a task on an employee's behalf.

## Validation performed
- Python source parsed and compiled successfully.
- All XML files parsed successfully.
- Obsolete `qa_reviewer_id` and `ab_approver_id` field references were removed.
- This is static validation only; the module has not been installed or functionally tested against the Odoo database.
