from odoo import models, fields, api, exceptions
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime
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
        ],
        ondelete={
            # This specifies what happens to records if '05_send_for_checking' is ever removed.
            # 'set 1_done' means tasks in this state will revert to 'Done'.
            '05_send_for_checking': 'set 1_done',
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
                    task.state in ('04_waiting_normal')
                    and not task.is_accepted
                    and not task.is_rejected
            )

    @api.depends('user_ids', 'project_id', 'is_locked')  # Add any fields that might influence assigner/assignee logic
    def _compute_is_editable_by_user(self):
        # Get the current user
        user = self.env.user

        # Get references to your custom groups
        group_assigner = self.env.ref('base.group_assigner')  # Replace with your actual group external ID
        group_assignee = self.env.ref('base.group_assignees')  # Replace with your actual group external ID

        for task in self:
            # Check if the user is in the Assigner group
            is_user_assigner = user.has_group('base.group_assigner')

            # Check if the user is in the Assignee group
            is_user_assignee = user.has_group('base.group_assignees')

            # Your logic: If the user is an Assigner, they can edit.
            # Otherwise, if they are only an Assignee, they cannot edit.
            if is_user_assigner:
                task.is_editable_to_user = True
            elif is_user_assignee:
                task.is_editable_to_user = False
            else:
                # Default case for users who are neither Assigner nor Assignee
                task.is_editable_to_user = False  # Or True, depending on your default policy

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
        # We need to get old_state for each task individually, BEFORE the super call updates them.
        old_states = {}
        for task in self:
            old_states[task.id] = task.state

            # Check for state changes from '03_approved' (Approved) to another state
            if 'state' in vals:
                new_state = vals['state']
                for task in self:
                    if old_states.get(task.id) == '03_approved' and new_state != '03_approved':
                        # The task is currently 'Approved' and the user is trying to change it to something else.
                        # Restrict this action.
                        raise UserError(
                            "This task is already Approved and cannot be moved out of the 'Approved' state.")

        res = super(ProjectTask, self).write(vals)  # Call original write method

        # Check conditions for each task individually after the write operation.
        for task in self:
            # Handle decrementing allowed_attempts when state changes to '05_send_for_checking'
            if 'state' in vals and vals['state'] == '05_send_for_checking' and old_states.get(
                    task.id) != '05_send_for_checking':
                if task.allowed_attempts > 0:
                    task.allowed_attempts -= 1
                else:
                    # You might want to prevent the state change if attempts are 0.
                    # This would require raising an error here before the write takes full effect.
                    # Example: raise UserError("No allowed attempts left to send for checking.")
                    pass
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
        if self.state not in '04_waiting_normal':
            raise UserError("This task cannot be accepted in its current state.")

        self.write(
            {'is_accepted': True, 'is_rejected': False, 'rejection_remarks': False, 'state': '01_in_progress'})  # Clear remarks on acceptance

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'form',
            'res_id': self.id,  # The ID of the current task
            'target': 'current',  # Open in the current window/tab
            'flags': {'action_texts': False},  # Optional: helps prevent extra text on the action
        }

    def action_reject_task(self):
        """
        Action for the 'Reject' button.
        Opens a wizard to enter rejection remarks.
        """
        self.ensure_one()
        if self.env.user not in self.user_ids:
            raise UserError("You are not an assignee of this task.")
        if not self.env.user.has_group('base.group_assignees'):
            raise UserError("You do not have the necessary permissions to reject this task.")

        # Check if already accepted or rejected
        if self.is_accepted:
            raise UserError("This task has already been accepted. You cannot reject an accepted task.")
        if self.is_rejected:
            raise UserError("This task has already been rejected.")

        # # Ensure the task is in a state where it can be rejected
        # if self.state not in ('1_done', '05_send_for_checking'):
        #     raise UserError("This task cannot be rejected in its current state.")

        return {
            'name': 'Reject Task',
            'type': 'ir.actions.act_window',
            'res_model': 'project.task.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info(f"Custom create method called with vals_list: {vals_list}")

        # Ensure vals_list is always a list for uniform processing
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        for vals in vals_list:
            # Check if 'state' is present in vals, AND if it's NOT already '04_waiting_normal'
            # This ensures we only override if it's different from our target default
            if 'state' in vals and vals['state'] != '04_waiting_normal':
                _logger.info(f"Overriding provided state '{vals['state']}' to '04_waiting_normal'.")
                vals['state'] = '04_waiting_normal'
            elif 'state' not in vals:
                # If 'state' is not in vals at all, then set our default
                vals['state'] = '04_waiting_normal'
                _logger.info(f"Setting default state to '04_waiting_normal' as it was not provided.")
            else:
                # If 'state' is already '04_waiting_normal', do nothing
                _logger.info(f"State '{vals['state']}' is already '04_waiting_normal'. No override needed.")

        # Call the original create method
        tasks = super(ProjectTask, self).create(vals_list)
        return tasks

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
