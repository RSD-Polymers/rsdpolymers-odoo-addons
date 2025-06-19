import typing

from odoo import models, fields, api, exceptions
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime
import logging # Import the logging module

_logger = logging.getLogger(__name__) # Initialize logger

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
            ('05_send_for_checking', 'Send for Checking'),  # Your new custom state
        ],
        ondelete={
            # This specifies what happens to records if '05_send_for_checking' is ever removed.
            # 'set 1_done' means tasks in this state will revert to 'Done'.
            '05_send_for_checking': 'set 1_done',
        }
    )

    # New field to indicate if the task is locked
    is_locked = fields.Boolean(string="Is Locked", compute="_compute_is_locked", store=True)

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
            if record.marks_obtained <= 0:
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
                        raise UserError("This task is already Approved and cannot be moved out of the 'Approved' state.")

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