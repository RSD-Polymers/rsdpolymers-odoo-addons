from odoo import models, fields, api, exceptions, _
from odoo.exceptions import ValidationError, UserError, AccessError
from datetime import date, datetime, timedelta
from odoo.osv import expression
import logging  # Import the logging module

_logger = logging.getLogger(__name__)  # Initialize logger


class ProjectTask(models.Model):
    _inherit = 'project.task'

    marks_obtained = fields.Float(string='Marks Obtained (out of 100)')
    allowed_attempts = fields.Integer(string='Number of Allowed Attempts', default=1)
    user_ids = fields.Many2many('res.users', relation='project_task_user_rel', column1='task_id', column2='user_id',
                                required=True, string='Assignees', context={'active_test': False}, tracking=True,
                                domain="[('share', '=', False), ('active', '=', True)]")
    checker_id = fields.Many2one(
        'res.users',
        string='Checker',
        # Use a lambda function to evaluate ref() at runtime when the environment is available
        domain=lambda self: [('groups_id', 'in', [self.env.ref('base.group_checker').id])],
        help="The user responsible for checking this task, restricted to Checker group.",
    )
    is_checker_field = fields.Boolean(compute="_compute_is_checker_field")
    is_assigner_field = fields.Boolean(compute="_compute_is_assigner_field")
    is_assignees_group_member = fields.Boolean(
        string="Is Assignees Group Member",
        compute='_compute_is_assignees_group_member',
        store=False,  # No need to store this in the database, it's dynamic
    )

    # Define the 'state' field to extend its selection options
    state = fields.Selection(
        selection_add=[
            ('05_send_for_checking', 'Send for Checking'),
            ('06_rejected', 'Rejected'),
        ],
        ondelete={
            # This specifies what happens to records if '05_send_for_checking' is ever removed.
            # 'set 1_done' means tasks in this state will revert to 'Done'.
            '05_send_for_checking': 'set 1_done',
            '06_rejected': 'set 1_done',
        }
    )

    # New field to indicate if the task is locked
    is_locked = fields.Boolean(string="Is Locked", compute="_compute_is_locked", store=True)

    # This computed field will be True if the current user should be able to edit
    is_editable_to_user = fields.Boolean(
        string="Is Editable by User",
        compute='_compute_is_editable_by_user',
        store=False,  # No need to store this in the database
    )

    # New fields for accepted/rejected status
    is_accepted = fields.Boolean(string="Accepted", default=False, copy=False)
    is_rejected = fields.Boolean(string="Rejected", default=False, copy=False)
    rejection_remarks = fields.Text(string="Rejection Remarks", readonly=True)

    can_assignee_accept_reject = fields.Boolean(
        string="Can Assignee Accept/Reject",
        compute="_compute_can_assignee_accept_reject",
        store=False,
    )

    # --- NEW COMPUTED FIELD FOR SPECIFIC CHECKER ACCESS ---
    is_current_user_the_task_checker = fields.Boolean(
        string="Current User is Task's Checker",
        compute="_compute_is_current_user_the_task_checker",
        store=False,  # Not stored in DB as it's dynamic and user-specific
    )

    is_current_user_the_task_assignee = fields.Boolean(
        string="Current User is Task's Assignee",
        compute="_compute_is_current_user_the_task_assignee",
        store=False,  # Not stored in DB as it's dynamic and user-specific
    )

    is_admin_user = fields.Boolean(compute='_compute_is_admin_user')

    def _compute_is_admin_user(self):
        for record in self:
            record.is_admin_user = self.env.user.has_group('base.group_system')

    # New Validation to check marks_obtained field while approving the task
    @api.constrains('state', 'marks_obtained')
    def _check_marks_obtained_on_approval(self):
        """
        Ensures 'Marks Obtained' is filled with a positive value when the task is approved.
        """
        for task in self:
            _logger.info(
                f"Checking marks_obtained for task {task.name} (ID: {task.id}) on state change to {task.state}")
            # If the task is being transitioned to the 'Approved' state
            if task.state == '03_approved':
                # Check if marks_obtained is empty (False) or zero/negative
                if not task.marks_obtained or task.marks_obtained <= 0:
                    _logger.warning(
                        f"Validation failed for task {task.id}: marks_obtained is {task.marks_obtained} when state is {task.state}")
                    raise ValidationError(
                        _("Marks Obtained must be entered and be greater than Zero before marking the task as Approved."))

    @api.depends('checker_id')  # Recompute if the assigned checker changes
    @api.depends_context('uid')  # Recompute if the logged-in user changes
    def _compute_is_current_user_the_task_checker(self):
        current_user_id = self.env.user.id
        for task in self:
            # Check if a checker is assigned AND if the assigned checker's ID matches the current user's ID
            task.is_current_user_the_task_checker = (task.checker_id and task.checker_id.id == current_user_id)

    @api.depends('user_ids')  # Recompute if the assigned checker changes
    @api.depends_context('uid')  # Recompute if the logged-in user changes
    def _compute_is_current_user_the_task_assignee(self):
        current_user = self.env.user
        for task in self:
            task.is_current_user_the_task_assignee = current_user in task.user_ids

    @api.depends('state', 'user_ids', 'is_accepted', 'is_rejected', 'is_assignees_group_member',
                 'is_current_user_the_task_checker')
    def _compute_can_assignee_accept_reject(self):
        user = self.env.user

        is_user_in_assignees_group = user.has_group('base.group_assignees')
        is_user_in_checker_group = user.has_group('base.group_checker')

        for task in self:
            is_current_user_assigned_to_task = user in task.user_ids

            can_perform_action = False

            # Common conditions that must be met for either role
            common_state_conditions = (
                    task.state in ('04_waiting_normal') and
                    not task.is_accepted and
                    not task.is_rejected
            )

            if is_current_user_assigned_to_task and common_state_conditions:
                # Scenario 1: User is a direct assignee of the task AND is in the 'assignees' group
                if is_user_in_assignees_group:
                    can_perform_action = True
                # Scenario 2: User is a direct assignee of the task AND is in the 'checker' group
                # This explicitly handles your new requirement: checker assigned to task sees buttons.
                elif is_user_in_checker_group:
                    can_perform_action = True

            task.can_assignee_accept_reject = can_perform_action

    @api.depends('user_ids', 'project_id', 'is_locked')  # Add any fields that might influence assigner/assignee logic
    def _compute_is_editable_by_user(self):
        # Get the current user
        user = self.env.user

        is_user_admin = user.has_group('base.group_system')
        is_user_assigner = user.has_group('base.group_assigner')
        is_user_checker = user.has_group('base.group_checker')
        is_user_assignee = user.has_group('base.group_assignees')

        for task in self:
            # 1) New (unsaved) record → allow editing only if user has create access
            if not task.id:
                try:
                    self.env['project.task'].check_access('create')
                    task.is_editable_to_user = True
                except AccessError:
                    task.is_editable_to_user = False
                continue

            # 2) Only specific states are editable (adjust order if admin/assigner should override states)
            if task.state not in ['01_in_progress', '04_waiting_normal']:
                task.is_editable_to_user = False
                continue

            # 3) Priority rules for existing records
            if is_user_admin:
                task.is_editable_to_user = True
                continue

            # Guard create_uid before comparing — avoids failures for records without it
            if is_user_assigner and task.create_uid and task.create_uid.id == user.id:
                task.is_editable_to_user = True
                continue

            if is_user_checker and task.is_current_user_the_task_checker:
                task.is_editable_to_user = True
                continue

            # 4) Assignees (explicitly assigned users) or members of assignee group -> read-only
            if (is_user_assigner and user in task.user_ids) or (user in task.user_ids):
                task.is_editable_to_user = False
                continue

            # Default
            task.is_editable_to_user = False

    @api.depends_context('uid')
    def _compute_is_checker_field(self):
        user = self.env.user
        has_checker_group = user.has_group("base.group_checker")
        for record in self:
            record.is_checker_field = has_checker_group

    @api.depends_context('uid')
    def _compute_is_assigner_field(self):
        user = self.env.user
        has_assigner_group = user.has_group("base.group_assigner")
        for record in self:
            record.is_assigner_field = has_assigner_group

    @api.depends_context('uid')  # Ensures recomputation if user changes
    def _compute_is_assignees_group_member(self):
        # Using self.env.user directly in compute method is correct
        for record in self:
            # Replace 'base.group_assignees' with the actual XML ID of your Assignees group
            # Common ones are 'project.group_project_user' or 'project.group_project_manager'
            record.is_assignees_group_member = self.env.user.has_group('base.group_assignees')
            # If your assignees group is specific to 'project' module, it might be 'project.group_project_user' or a custom one.
            # Example: record.is_assignees_group_member = self.env.user.has_group('project.group_project_user')

    @api.constrains('date_deadline')
    def _check_date_deadline_not_past(self):
        """
        Validates that the date_deadline is not a past date.
        Ensures comparison is always between datetime.date objects.
        """
        for task in self:

            if not task.date_deadline:
                raise ValidationError("The Deadline field cannot be empty. Please enter it!!")

            if task.date_deadline:
                # Ensure today's date is a datetime.date object
                today_date = date.today()
                deadline_date_only = task.date_deadline.date() if isinstance(task.date_deadline,
                                                                             datetime) else task.date_deadline
                if deadline_date_only < today_date:
                    raise ValidationError(
                        "The Deadline field cannot accept past dates. Please select today's date or a future date.")

    @api.constrains('checker_id')
    def _check_checker_field(self):
        for task in self:
            if not task.checker_id:
                raise ValidationError("You can't leave the Checker field empty.")

    @api.constrains('allowed_attempts')
    def _check_allowed_attempts(self):
        for rec in self:
            if rec.allowed_attempts < 0:
                raise exceptions.ValidationError("Number of Allowed Attempts cannot be negative.")
            if rec.allowed_attempts > 5:
                raise exceptions.ValidationError("Checkers can assign a maximum of Five allowed attempts.")

    @api.constrains('marks_obtained')
    def _check_marks_obtained_max_value(self):
        for record in self:
            if record.marks_obtained > 100:
                raise ValidationError("Marks Obtained (out of 100) cannot exceed 100.")
            if record.marks_obtained < 0:
                raise ValidationError("Marks Obtained (out of 100) cannot be Zero or Negative.")

    @api.depends('state')
    def _compute_is_locked(self):
        for task in self:
            task.is_locked = (task.state == '03_approved')

    def create(self, vals_list):
        """
        Overrides the create method to ensure the default state is '04_waiting_normal'
        when a new task is created, overriding the default '01_in_progress' if present.
        """
        _logger.info(f"*** CREATE METHOD STARTED for ProjectTask ***")
        _logger.info(f"Incoming 'vals_list' for create: {vals_list}")
        # Ensure vals_list is always a list, even if a single dict is passed (for robustness)
        if not isinstance(vals_list, list):
            vals_list = [vals_list]

        modified_vals_list = []
        for vals in vals_list:
            # Create a mutable copy of the dictionary to modify
            current_vals = dict(vals)
        # Check if 'state' is not provided OR if it's explicitly '01_in_progress' (Odoo's default for new tasks)
        # If it's '01_in_progress', we assume it's the unwanted default and override it.
        if 'state' not in current_vals or current_vals.get('state') == '01_in_progress':
            current_vals['state'] = '04_waiting_normal'
            _logger.info(f"Overriding state to: {current_vals['state']} (was not provided or was '01_in_progress')")
        else:
            _logger.info(f"State already provided in vals and is not '01_in_progress': {current_vals['state']}")

        if current_vals.get('parent_id') and not current_vals.get('date_deadline'):
            parent_task = self.browse(current_vals['parent_id'])
            if parent_task.date_deadline:
                current_vals['date_deadline'] = parent_task.date_deadline
                _logger.info(
                    f"Inheriting deadline {current_vals['date_deadline']} "
                    f"from parent task ID {parent_task.id}"
                )

        modified_vals_list.append(current_vals)
        # Call the original create method with the (potentially modified) vals
        tasks = super(ProjectTask, self).create(modified_vals_list)
        for task in tasks:
            _logger.info(f"Task '{task.name}' (ID: {task.id}) created with state: {task.state}")
        return tasks  # <--- Return the recordset of created tasks

    def write(self, vals):
        is_action_specific_write = self.env.context.get('is_action_specific_task_op', False)

        _logger.info(f"*** WRITE METHOD STARTED for Task IDs: {self.ids} ***")
        _logger.info(f"Incoming 'vals' for write: {vals}")
        original_vals = {
            task.id: {'is_accepted': task.is_accepted, 'is_rejected': task.is_rejected, 'state': task.state,
                      'allowed_attempts': task.allowed_attempts} for task in self}
        _logger.info(f"Original values from ORM (self object) at start of write: {original_vals}")
        _logger.info(f"is_action_specific_task_op (from context): {is_action_specific_write}")

        for task in self:
            _logger.info(f"--- Processing Task ID: {task.id} ---")
            original_state = original_vals[task.id]['state']
            original_is_rejected = original_vals[task.id]['is_rejected']
            _logger.info(
                f"Task {task.id}: original_state={original_state}, original_is_rejected={original_is_rejected}")

            # --- NEW VALIDATION: ALLOCATED TIME AFTER DEADLINE IS SET ---
            if 'allocated_hours' in vals and task.date_deadline:
                _logger.warning(
                    f"Task {task.id}: Blocking 'allocated_time' update. A deadline has already been set.")
                raise UserError(_("The allocated time cannot be edited once a deadline has been set."))

            # --- NEW VALIDATION: MARKS OBTAINED IN 'IN PROGRESS' STATE ---
            if 'marks_obtained' in vals and task.state == '01_in_progress':
                _logger.warning(
                    f"Task {task.id}: Blocking 'marks_obtained' update. Task is in 'In Progress' state.")
                raise UserError(_("Marks Obtained cannot be given when the task is in the 'In Progress' state."))

            # --- VALIDATION LOGIC FOR TRANSITIONING *TO* '05_send_for_checking' STATE ---
            if 'state' in vals and vals['state'] == '05_send_for_checking':
                if not task.is_accepted:
                    _logger.warning(
                        f"Task {task.id}: Blocking state change to 'Send for Checking'. Task has not been accepted yet.")
                    raise UserError(_("You must accept the task before sending it for checking."))

                if task.allowed_attempts <= 0:
                    _logger.warning(
                        f"Task {task.id}: Blocking state change to 'Send for Checking'. Allowed attempts are {task.allowed_attempts}.")
                    raise UserError(
                        _("Cannot send for checking: Number of allowed attempts are exhausted for this task."))

                if self.env.user not in task.user_ids:
                    _logger.warning(
                        f"Task {task.id}: Blocking state change to 'Send for Checking'. Current user {self.env.user.name} is not an assignee.")
                    raise UserError(
                        _("You are not the right person to do Send For Checking. Only an assignee of this task can set its state to 'Send for Checking'."))

                task.allowed_attempts -= 1
                _logger.info(
                    f"Task {task.id}: Decremented allowed_attempts to {task.allowed_attempts} due to state change to 'Send for Checking'.")

            # --- VALIDATION LOGIC FOR WHEN TASK IS *ALREADY IN* A SPECIFIC STATE ---
            elif self.env.user.has_group('base.group_system'):
                _logger.info(f"Task {task.id}: Admin bypass enabled. Skipping modification validation for non-admin.")
                pass
            elif original_state == '06_rejected' or original_is_rejected:
                _logger.info(
                    f"Task {task.id}: Original state is '{original_state}'. Checking conditions for modification.")
                is_unrejecting = ('is_rejected' in vals and vals['is_rejected'] is False)
                is_changing_from_rejected_state = ('state' in vals and vals['state'] != '06_rejected')

                if is_action_specific_write or is_unrejecting or is_changing_from_rejected_state:
                    _logger.info(
                        f"Task {task.id}: Allowing modification due to action-specific write or un-reject/state change.")
                    pass
                else:
                    _logger.warning(
                        f"Task {task.id}: Blocking modification. Task is in 'Rejected' state and no un-reject/re-rejection action detected. vals={vals}")
                    raise UserError(_("This task is in a 'Rejected' state and cannot be modified."))


            elif original_state == '03_approved':
                _logger.info(
                    f"Task {task.id}: Original state is '{original_state}'. Checking conditions for modification from Approved.")
                # Define fields that are considered "safe" for Odoo's internal updates when in '03_approved' state

                safe_approved_fields = [
                    'create_date', 'write_date', 'write_uid', 'display_name',
                    'activity_exception_decoration', 'activity_state', 'activity_summary',
                    'activity_ids', 'message_follower_ids', 'message_ids', 'message_is_follower',
                    'message_unread', 'message_unread_counter', 'portal_url', 'access_token',
                    'kanban_state_label', 'stage_id',
                    'date_last_stage_update'  # ADD THIS FIELD HERE
                ]
                if not is_action_specific_write:
                    if 'state' in vals and vals['state'] != '03_approved':
                        _logger.warning(
                            f"Task {task.id}: Blocking modification. Task is in 'Approved' state and state change detected. vals={vals}")
                        raise UserError(_("This task is in an 'Approved' state and its state cannot be changed."))

                    elif any(field in vals for field in vals if
                             field not in safe_approved_fields):  # Use safe_approved_fields here

                        _logger.warning(
                            f"Task {task.id}: Blocking modification of other fields. Task is in 'Approved' state. Vals: {vals}")
                        raise UserError(
                            _("This task is in an 'Approved' state and cannot be modified except by specific actions."))

            # --- MODIFIED BLOCK FOR '05_send_for_checking' ---
            elif original_state == '05_send_for_checking':
                _logger.info(
                    f"Task {task.id}: Original state is 'Send for Checking'. Checking permissions for modification by user {self.env.user.name}.")

                # Define fields that are considered "safe" for Odoo's internal updates
                # These typically include timestamp fields, activity-related fields, etc.
                safe_fields = [
                    'write_date', 'date_last_stage_update', 'activity_ids', 'activity_state',
                    'activity_summary', 'message_follower_ids', 'message_ids', 'message_is_follower',
                    'message_unread', 'message_unread_counter', 'portal_url', 'access_token',
                    'kanban_state_label', 'stage_id'  # Stage_id is also often updated internally or by computed fields
                ]

                # Check if the current user is NOT the designated checker AND NOT an admin
                if not task.is_current_user_the_task_checker and not self.env.user.has_group('base.group_system'):
                    # If there are ANY fields in 'vals' that are NOT in our 'safe_fields' list,
                    # AND the 'state' field itself is not the ONLY field being changed, then block the modification.
                    # Note: The initial 'if' handles actual state changes TO '05_send_for_checking'.
                    # This 'elif' handles writes WHEN task is ALREADY '05_send_for_checking'.
                    # We check if 'vals' contains any keys that are not safe fields.
                    if any(field not in safe_fields for field in vals):
                        _logger.warning(
                            f"Task {task.id}: Blocking modification of unsafe fields. User {self.env.user.name} is not the designated checker or admin, and task is 'Send for Checking'. Vals: {vals}")
                        raise UserError(
                            _("Only the designated Checker can make any changes once the task is in 'Send for Checking'."))
                    else:
                        _logger.info(
                            f"Task {task.id}: Non-checker/non-admin user {self.env.user.name} is modifying only safe fields in 'Send for Checking'. Allowed. Vals: {vals}")
                else:
                    _logger.info(
                        f"Task {task.id}: User {self.env.user.name} (Checker/Admin) is modifying task in 'Send for Checking'. Allowed.")

        res = super(ProjectTask, self).write(vals)
        for task_rec in self:
            _logger.info(
                f"Task {task_rec.name} (ID: {task_rec.id}) - Write completed. Current state: {task_rec.state}, Is Accepted: {task_rec.is_accepted}")
        return res

    def unlink(self):
        """
        Prevents deletion of tasks that are in the '03_approved' state.
        """
        for task in self:
            if task.state == '03_approved':
                raise UserError("You cannot delete a task that is in 'Approved' state.")
        return super(ProjectTask, self).unlink()

    def action_accept_task(self):
        """
        Action for the 'Accept' button.
        Marks the task as 'Accepted' and changes state to 'In Progress'.
        """
        self.ensure_one()
        if self.allowed_attempts <= 0:
            raise UserError(_("Cannot accept this task: No allowed attempts remaining."))

        if self.env.user not in self.user_ids:
            raise UserError("You are not an assignee of this task.")
        if not self.env.user.has_group('base.group_assignees'):
            raise UserError("You do not have the necessary permissions to accept this task.")

        # Check if already accepted or rejected
        if self.is_accepted:
            raise UserError("This task has already been accepted.")
        if self.is_rejected:
            raise UserError("This task has already been rejected. Please correct it first.")

        # Ensure the task is in a state where it can be accepted
        if self.state not in '04_waiting_normal':
            raise UserError("This task cannot be accepted in its current state.")

        # Calculate the 48-hour threshold from the task's creation date
        threshold_time = self.create_date + timedelta(hours=48)
        now_utc = fields.Datetime.now()

        _logger.info(
            f"Task {self.id} - Create Date: {self.create_date}, Threshold: {threshold_time}, Current Time: {now_utc}")

        # If the current time is past the 48-hour threshold, restrict acceptance.
        if now_utc > threshold_time:
            # IMPORTANT: We only raise an error here. We DO NOT change the state to 'rejected'.
            # The cron job is responsible for that actual state transition.
            raise UserError(_("This task cannot be accepted as the 48-hour acceptance window has expired."))

        self.write(
            {'is_accepted': True, 'is_rejected': False, 'rejection_remarks': False,
             'state': '01_in_progress'})  # Clear remarks on acceptance
        _logger.info(f"Task {self.name} accepted. State changed to 'In Progress'.")

        self.message_post(
            body=_("Task has been **Accepted** and moved to 'In Progress'."),
            subject=_("Task Acceptance")
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'form',
            'res_id': self.id,  # The ID of the current task
            'target': 'current',  # Open in the current window/tab
            'flags': {'action_texts': False},  # Optional: helps prevent extra text on the action
        }

    def action_reject_task(self):
        self.ensure_one()
        if self.env.user not in self.user_ids:
            raise UserError("You are not an assignee of this task.")
        if not self.env.user.has_group('base.group_assignees'):
            raise UserError("You do not have the necessary permissions to reject this task.")

        if self.is_accepted:
            raise UserError("This task has already been accepted. You cannot reject an accepted task.")
        # Ensure that if it's already in the '06_rejected' state, you cannot reject it again
        # This prevents opening the wizard if it's already fully rejected.
        if self.state == '06_rejected':  # <--- UPDATED: Check for '06_rejected'
            raise UserError(_("This task is already in 'Rejected' state."))
        if self.is_rejected and self.state != '06_rejected':  # This case should ideally not happen if state aligns with is_rejected
            raise UserError("This task has already been rejected (flag is true).")

        # Ensure the task is in a state where it can be rejected
        if self.state in ('1_done', '05_send_for_checking'):
            raise UserError("This task cannot be rejected in its current state.")

        return {
            'name': 'Reject Task',
            'type': 'ir.actions.act_window',
            'res_model': 'project.task.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }

    def _inverse_state(self):
        """
        Original _inverse_state method. The validation for '05_send_for_checking'
        has been moved to the 'write' method for centralized control.
        This method can be removed if no other logic relies on it.
        """
        # The validation for '05_send_for_checking' and not task.is_accepted
        # has been moved to the 'write' method.
        # This _inverse_state method can now be simplified or removed if no other
        # inverse logic is required for the 'state' field.
        pass

    @api.model
    def _cron_auto_reject_unaccepted_tasks(self):
        _logger.info("Cron job: Checking for unaccepted tasks...")

        # Get the current UTC time using Odoo's Datetime field helper
        now_utc = fields.Datetime.now()
        # Calculate the threshold time: 48 hours ago from now (UTC)
        threshold_time = now_utc - timedelta(hours=48)

        # Find tasks that meet the criteria:
        # 1. Are in the 'Waiting' state ('04_waiting_normal')
        # 2. Have NOT been accepted (is_accepted = False)
        # 3. Were created more than 48 hours ago
        tasks_to_reject = self.search([
            ('state', '=', '04_waiting_normal'),
            ('is_accepted', '=', False),
            ('create_date', '<=', threshold_time),
        ])

        # Add these lines for debugging and logging
        _logger.info(f"Search query returned: {tasks_to_reject}")
        _logger.info(f"Type of tasks_to_reject: {type(tasks_to_reject)}")
        _logger.info(f"Number of tasks found: {len(tasks_to_reject)}")

        if tasks_to_reject:
            _logger.info(f"Found {len(tasks_to_reject)} tasks to auto-reject.")
            for task in tasks_to_reject:
                # Update the task's status to rejected and change its state
                task.write({
                    'is_rejected': True,
                    'is_accepted': False,  # Ensure it's explicitly False
                    'rejection_remarks': _("Task automatically rejected: Not accepted by assignee within 48 hours."),
                    'state': '06_rejected',
                })
                _logger.info(f"Task '{task.name}' (ID: {task.id}) auto-rejected.")

                # Optionally, post a message on the task's chatter for visibility
                task.message_post(
                    body=_("Task automatically marked as rejected because it was not accepted within 48 hours."),
                    subject=_("Task Auto-Rejection Notification"),
                    # You can add specific partners to notify if desired:
                    # partner_ids=[task.user_id.partner_id.id] if task.user_id else [],
                )
        else:
            _logger.info("No unaccepted tasks found requiring auto-rejection.")

    # Removing search method as it is creating a lot of issues in Project Task. So record rules are used for this
    # @api.model
    # def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
    #     original_domain = list(args) if args is not None else []  # Ensure original_domain is a mutable list
    #     final_domain = []
    #
    #     # Initialize custom_filter at the very beginning to prevent UnboundLocalError
    #     custom_filter = []
    #
    #     current_user = self.env.user
    #
    #     # 1. Administrator Bypass:
    #     if current_user.has_group('base.group_system'):
    #         final_domain = original_domain
    #     else:
    #         # Check for Nilesh Bagwe specifically
    #         nilesh_bagwe_user = self.env['res.users'].sudo().search([('login', '=', 'nilesh@rsdpolymers.com')], limit=1)
    #
    #         if nilesh_bagwe_user and current_user == nilesh_bagwe_user:
    #             _logger.info("Nilesh Bagwe (%s) detected.", current_user.name)
    #             qc_department_id = self.env.ref('hr.dep_qc', raise_if_not_found=False).id
    #             qa_department_id = self.env.ref('hr.dep_qa', raise_if_not_found=False).id
    #             store_department_id = self.env.ref('hr.dep_store', raise_if_not_found=False).id
    #             production_department_id = self.env.ref('hr.dep_production', raise_if_not_found=False).id
    #
    #             nilesh_specific_dept_ids = [did for did in [qc_department_id, qa_department_id, store_department_id,
    #                                                         production_department_id] if did]
    #
    #             if nilesh_specific_dept_ids:
    #                 custom_filter = [
    #                     '|', '|',
    #                     ('user_ids', 'in', current_user.id),
    #                     ('checker_id', '=', current_user.id),
    #                     ('user_ids.employee_ids.department_id', 'in', nilesh_specific_dept_ids)
    #                 ]
    #             else:
    #                 custom_filter = [
    #                     '|',
    #                     ('user_ids', 'in', current_user.id),
    #                     ('checker_id', '=', current_user.id),
    #                 ]
    #         else:
    #             # Logic for all other non-admin, non-Nilesh users
    #
    #             # IMPORTANT: Replace these with the actual External IDs of Parikshit's relevant groups
    #             # You must get these from Settings -> Technical -> Security -> Groups
    #             is_time_off_manager = current_user.has_group('hr_holidays.group_hr_holidays_manager')
    #             is_hr_manager = current_user.has_group('hr.group_hr_manager')  # Standard Odoo group
    #             is_project_administrator = current_user.has_group(
    #                 'project.group_user_l3')  # Standard Odoo group
    #             is_time_off_user = current_user.has_group('hr_holidays.group_hr_holidays_user')
    #
    #             if is_time_off_manager or is_hr_manager or is_project_administrator or is_time_off_user:
    #                 _logger.info("User is detected as a Manager/Approver (Time Off: %s, HR: %s, Project: %s).",
    #                              is_time_off_manager, is_hr_manager, is_project_administrator)
    #                 # Broaden access for managers/approvers
    #                 custom_filter = [
    #                     '|',  # OR condition for the first two items
    #                     ('user_ids', 'in', current_user.id),
    #                     '|',  # OR condition for the next two items
    #                     ('checker_id', '=', current_user.id),
    #                     ('project_id.user_id', '=', current_user.id)
    #                 ]
    #             else:
    #                 # Default filter for regular users (assigned or checker)
    #                 custom_filter = [
    #                     '|',
    #                     ('user_ids', 'in', current_user.id),
    #                     ('checker_id', '=', current_user.id),
    #                 ]
    #
    #     # Combine custom filter with original domain
    #     if custom_filter:
    #         if original_domain:
    #             final_domain = ['&'] + original_domain + custom_filter
    #         else:
    #             final_domain = custom_filter
    #     else:
    #         final_domain = original_domain
    #
    #     # Pass all original args/kwargs to super, but replace the domain part
    #     return super()._search(final_domain, offset=offset, limit=limit, order=order)