from odoo import models, fields, api, exceptions, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime, timedelta
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

    @api.depends('state', 'user_ids', 'is_accepted', 'is_rejected', 'is_assignees_group_member')
    def _compute_can_assignee_accept_reject(self):
        for task in self:
            is_assignee_of_task = self.env.user in task.user_ids

            task.can_assignee_accept_reject = (
                    is_assignee_of_task and
                    task.is_assignees_group_member and
                    task.state in ('01_in_progress')
                    and not task.is_accepted
                    and not task.is_rejected
            )

    @api.depends('user_ids', 'project_id', 'is_locked')  # Add any fields that might influence assigner/assignee logic
    def _compute_is_editable_by_user(self):
        # Get the current user
        user = self.env.user

        is_user_admin = user.has_group('base.group_system')
        is_user_assigner = user.has_group('base.group_assigner') # REMEMBER TO REPLACE THIS
        is_user_assignee = user.has_group('base.group_assignees') # REMEMBER TO REPLACE THIS

        for task in self:
            # Admins can always edit, overriding other restrictions
            if is_user_admin:
                task.is_editable_to_user = True
            # If not admin, check Assigner
            elif is_user_assigner:
                task.is_editable_to_user = True
            # If not admin or assigner, check Assignee
            elif is_user_assignee:
                task.is_editable_to_user = False  # Assignees cannot edit based on your original logic
            else:
                # Default case for users who are neither Admin, Assigner, nor Assignee
                # Set this based on your default policy for other users
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
            if rec.allowed_attempts <= 0:
                raise exceptions.ValidationError("Number of Allowed Attempts can't be Zero.")
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

    def write(self, vals):
        # Retrieve the flag from the environment context
        is_action_specific_write = self.env.context.get('is_action_specific_task_op', False) # Use a more descriptive name for clarity

        # Your logging lines
        _logger.info(f"*** WRITE METHOD STARTED for Task IDs: {self.ids} ***")
        _logger.info(f"Incoming 'vals' for write: {vals}")
        original_vals = {task.id: {'is_accepted': task.is_accepted, 'is_rejected': task.is_rejected, 'state': task.state} for task in self}
        _logger.info(f"Original values from ORM (self object) at start of write: {original_vals}")
        _logger.info(f"is_action_specific_task_op (from context): {is_action_specific_write}") # Updated log name

        for task in self:
            _logger.info(f"--- Processing Task ID: {task.id} ---")
            original_state = original_vals[task.id]['state']
            original_is_rejected = original_vals[task.id]['is_rejected']
            _logger.info(f"Task {task.id}: original_state={original_state}, original_is_rejected={original_is_rejected}")

            # VALIDATION LOGIC:
            # 1. Allow Admins to bypass any state-based restrictions for writes.
            if self.env.user.has_group('base.group_system'):
                _logger.info(f"Task {task.id}: Admin bypass enabled. Skipping modification validation.")
                pass # Admin can proceed, no blocking needed here
            # 2. If the task is already in a 'rejected' state OR `is_rejected` is True
            #    AND this is NOT an explicit action's write (is_action_specific_task_op = False)
            elif (original_state == '06_rejected' or original_is_rejected):
                _logger.info(f"Task {task.id}: Original state is '{original_state}'. Checking conditions for modification.")

                # Check if the current write is attempting to un-reject the task
                is_unrejecting = ('is_rejected' in vals and vals['is_rejected'] is False)
                # Check if the current write is attempting to change state away from rejected
                is_changing_from_rejected_state = ('state' in vals and vals['state'] != '06_rejected')

                # If it's the specific action (context flag) OR it's trying to un-reject/change state from rejected, allow it.
                if is_action_specific_write or is_unrejecting or is_changing_from_rejected_state:
                    _logger.info(f"Task {task.id}: Allowing modification due to action-specific write or un-reject/state change.")
                    pass # Allow the write
                else:
                    # BLOCK if it's already rejected and not an un-reject/state change action, and not admin
                    _logger.warning(f"Task {task.id}: Blocking modification. Task is in 'Rejected' state and no un-reject/re-rejection action detected. vals={vals}")
                    raise UserError(_("This task is in a 'Rejected' state and cannot be modified."))

            # Add similar logic for 'is_locked' if you have a separate lock mechanism that blocks modification.

        # Proceed with the original write operation after all checks
        res = super(ProjectTask, self).write(vals)
        _logger.info(f"Task {self.name} - Write completed. Current state: {self.state}, Is Accepted: {self.is_accepted}")
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
        Marks the task as 'Accepted'.
        """
        self.ensure_one()
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
        if self.state not in '01_in_progress':
            raise UserError("This task cannot be accepted in its current state.")

        self.write(
            {'is_accepted': True, 'is_rejected': False, 'rejection_remarks': False})  # Clear remarks on acceptance

        self.message_post(
            body=_("Task has been **Accepted**"),
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
        if self.state == '06_rejected': # <--- UPDATED: Check for '06_rejected'
            raise UserError(_("This task is already in 'Rejected' state."))
        if self.is_rejected and self.state != '06_rejected': # This case should ideally not happen if state aligns with is_rejected
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
        Custom inverse method for the 'state' field.
        Applies validation rules before state changes are committed.
        """
        for task in self:
            # Get the original state before the write operation
            # This requires getting the original value before the current transaction's changes
            # are committed. A common pattern for this is to use a `write` override,
            # or ensure you are comparing against the *previous* value for validation.

            # Simplified approach for this inverse: check the new value and existing conditions
            # The 'state' field itself is being set on 'task', so task.state already has the new value.

            _logger.info(
                f"Task {task.name} - Inverse state called. Current state: {task.state}, Is Accepted: {task.is_accepted}")

            # Check if the task is being transitioned TO '05_send_for_checking'
            # AND if the task has NOT been accepted yet.
            if task.state == '05_send_for_checking' and not task.is_accepted:
                # Check if the current user is an assignee attempting this transition
                # This check ensures the restriction applies to assignees.
                is_assignee_of_task = self.env.user in task.user_ids
                if is_assignee_of_task and self.env.user.has_group('base.group_assignees'):
                    raise UserError("You must accept the task before sending it for checking.")

            pass  # No explicit assignment needed if 'state' is the primary stored field

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
            ('state', '=', '01_in_progress'),
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