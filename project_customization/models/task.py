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

    # --- NEW COMPUTED FIELD FOR SPECIFIC CHECKER ACCESS ---
    is_current_user_the_task_checker = fields.Boolean(
        string="Current User is Task's Checker",
        compute="_compute_is_current_user_the_task_checker",
        store=False,  # Not stored in DB as it's dynamic and user-specific
    )

    # New Validation to check marks_obtained field while approving the task
    @api.constrains('state', 'marks_obtained')
    def _check_marks_obtained_on_approval(self):
        """
        Ensures 'Marks Obtained' is filled with a positive value when the task is approved.
        """
        for task in self:
            _logger.info(f"Checking marks_obtained for task {task.name} (ID: {task.id}) on state change to {task.state}")
            # If the task is being transitioned to the 'Approved' state
            if task.state == '03_approved':
                # Check if marks_obtained is empty (False) or zero/negative
                if not task.marks_obtained or task.marks_obtained <= 0:
                    _logger.warning(f"Validation failed for task {task.id}: marks_obtained is {task.marks_obtained} when state is {task.state}")
                    raise ValidationError(_("Marks Obtained must be entered and be greater than Zero before marking the task as Approved."))

    @api.depends('checker_id')  # Recompute if the assigned checker changes
    @api.depends_context('uid')  # Recompute if the logged-in user changes
    def _compute_is_current_user_the_task_checker(self):
        current_user_id = self.env.user.id
        for task in self:
            # Check if a checker is assigned AND if the assigned checker's ID matches the current user's ID
            task.is_current_user_the_task_checker = (task.checker_id and task.checker_id.id == current_user_id)

    @api.depends('state', 'user_ids', 'is_accepted', 'is_rejected', 'is_assignees_group_member', 'is_current_user_the_task_checker')
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
        is_user_assigner = user.has_group('base.group_assigner') # REMEMBER TO REPLACE THIS
        is_user_assignee = user.has_group('base.group_assignees') # REMEMBER TO REPLACE THIS
        is_user_checker = user.has_group('base.group_checker')

        for task in self:
            # Determine if the task is in an "editable" state based on the provided 'state' field values.
            # '01_in_progress' and '04_waiting_normal' are the states that should allow editing.
            is_in_editable_state = task.state in ['01_in_progress', '04_waiting_normal']

            # Rule 1: If the task is NOT in an editable state, it's immediately not editable.
            if not is_in_editable_state:
                task.is_editable_to_user = False
                continue  # Move to the next task

            # Rule 2: Admins can always edit
            if is_user_admin:
                task.is_editable_to_user = True
            # Rule 3: Users in the 'Assigner' group (who assign tasks) can edit
            elif is_user_assigner:
                task.is_editable_to_user = True
            # Rule 4: Users in the 'Checker' group (who check tasks) can edit
            # This is the new rule that was missing!
            elif is_user_checker:
                task.is_editable_to_user = True
            # Rule 5: If the user is in the 'Assignees' group, they cannot edit (as per your requirement)
            elif is_user_assignee:
                task.is_editable_to_user = False
            # Rule 6: If the current user is a direct assignee of THIS task (in user_ids)
            # but is not an admin, assigner, or checker group member
            elif user in task.user_ids:
                task.is_editable_to_user = False  # Still cannot edit if just an assignee
            else:
                # Default case for any other user
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
        original_vals = {task.id: {'is_accepted': task.is_accepted, 'is_rejected': task.is_rejected, 'state': task.state, 'allowed_attempts': task.allowed_attempts} for task in self}
        _logger.info(f"Original values from ORM (self object) at start of write: {original_vals}")
        _logger.info(f"is_action_specific_task_op (from context): {is_action_specific_write}")

        for task in self:
            _logger.info(f"--- Processing Task ID: {task.id} ---")
            original_state = original_vals[task.id]['state']
            original_is_rejected = original_vals[task.id]['is_rejected']
            _logger.info(f"Task {task.id}: original_state={original_state}, original_is_rejected={original_is_rejected}")

            # --- NEW VALIDATION LOGIC FOR 'SEND FOR CHECKING' STATE ---
            if 'state' in vals and vals['state'] == '05_send_for_checking':
                # Check if the task has been accepted BEFORE allowing 'Send for Checking'
                if not task.is_accepted:
                    _logger.warning(f"Task {task.id}: Blocking state change to 'Send for Checking'. Task has not been accepted yet.")
                    raise UserError(_("You must accept the task before sending it for checking."))

                # 1. Restrict if no attempts left BEFORE checking assignee or decrementing
                if task.allowed_attempts <= 0:
                    _logger.warning(f"Task {task.id}: Blocking state change to 'Send for Checking'. Allowed attempts are {task.allowed_attempts}.")
                    raise UserError(_("Cannot send for checking: Number of allowed attempts are exhausted for this task."))

                # 2. Check if the current user is an assignee of the task
                if self.env.user not in task.user_ids:
                    _logger.warning(f"Task {task.id}: Blocking state change to 'Send for Checking'. Current user {self.env.user.name} is not an assignee.")
                    raise UserError(_("You are not the right person to do Send For Checking. Only an assignee of this task can set its state to 'Send for Checking'."))
                # 3. Decrement allowed_attempts when sending for checking
                task.allowed_attempts -= 1
                _logger.info(f"Task {task.id}: Decremented allowed_attempts to {task.allowed_attempts} due to state change to 'Send for Checking'.")
                # --- END 'SEND FOR CHECKING' LOGIC ---

            # VALIDATION LOGIC:
            # 1. Allow Admins to bypass any state-based restrictions for writes.
            if self.env.user.has_group('base.group_system'):
                _logger.info(f"Task {task.id}: Admin bypass enabled. Skipping modification validation.")
                pass
            # 2. If the task is already in a 'rejected' state OR `is_rejected` is True
            elif original_state == '06_rejected' or original_is_rejected:
                _logger.info(f"Task {task.id}: Original state is '{original_state}'. Checking conditions for modification.")
                is_unrejecting = ('is_rejected' in vals and vals['is_rejected'] is False)
                is_changing_from_rejected_state = ('state' in vals and vals['state'] != '06_rejected')

                if is_action_specific_write or is_unrejecting or is_changing_from_rejected_state:
                    _logger.info(f"Task {task.id}: Allowing modification due to action-specific write or un-reject/state change.")
                    pass
                else:
                    _logger.warning(f"Task {task.id}: Blocking modification. Task is in 'Rejected' state and no un-reject/re-rejection action detected. vals={vals}")
                    raise UserError(_("This task is in a 'Rejected' state and cannot be modified."))

            # NEW VALIDATION: Prevent changes if the task is '03_approved'
            elif original_state == '03_approved':
                _logger.info(f"Task {task.id}: Original state is '{original_state}'. Checking conditions for modification from Approved.")
                # Allow specific changes from 'approved' if needed, for example, if an "Unapprove" or "Re-open" action exists.
                # Otherwise, block all state changes from approved.

                # Example: If you want to allow changing state to '1_done' from '03_approved', you could add:
                # if 'state' in vals and vals['state'] == '1_done':
                #    _logger.info(f"Task {task.id}: Allowing transition from Approved to Done.")
                #    pass
                # else:
                # Block all other modifications if it's approved and not an admin or specific action.
                if not is_action_specific_write: # You might have an 'unapprove' action that uses this context flag
                    # If the 'state' field is being changed AND the new state is NOT '03_approved'
                    if 'state' in vals and vals['state'] != '03_approved':
                        _logger.warning(f"Task {task.id}: Blocking modification. Task is in 'Approved' state and state change detected. vals={vals}")
                        raise UserError(_("This task is in an 'Approved' state and its state cannot be changed."))
                    # You might also want to prevent changes to other critical fields if approved, e.g.,
                    # if any(f in vals for f in ['user_ids', 'project_id']) and not is_action_specific_write:
                    #     raise UserError(_("This task is approved and cannot be modified."))

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
            {'is_accepted': True, 'is_rejected': False, 'rejection_remarks': False, 'state': '01_in_progress'})  # Clear remarks on acceptance
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

    def _search(self, *args, **kwargs):
        # Extract the original domain passed to this search method.
        original_domain = args[0] if args and isinstance(args[0], list) else []

        # Initialize the final domain that will be passed to super().
        final_domain = []

        current_user = self.env.user

        # 1. Administrator Bypass:
        # If the current user is an administrator, they see all tasks (no custom filter applied).
        if current_user.has_group('base.group_system'):
            final_domain = original_domain
        else:
            # Determine the custom filter based on the current user's type and roles.
            custom_filter = []

            # 2. Identify 'nilesh@rsdpolymers.com' user specifically.
            # Use .sudo() to ensure the search for this specific user is always allowed,
            # regardless of the current user's access rights.
            nilesh_bagwe_user = self.env['res.users'].sudo().search([('login', '=', 'nilesh@rsdpolymers.com')], limit=1)

            if nilesh_bagwe_user and current_user == nilesh_bagwe_user:
                # Specific logic for 'nilesh@rsdpolymers.com' user:
                # Get the IDs of specific departments (QC, QA, Store).
                # Handle cases where departments might not be found using raise_if_not_found=False.
                qc_department_id = self.env.ref('hr.dep_qc', raise_if_not_found=False).id if self.env.ref('hr.dep_qc',
                                                                                                          raise_if_not_found=False) else False
                qa_department_id = self.env.ref('hr.dep_qa', raise_if_not_found=False).id if self.env.ref('hr.dep_qa',
                                                                                                          raise_if_not_found=False) else False
                store_department_id = self.env.ref('hr.dep_store', raise_if_not_found=False).id if self.env.ref(
                    'hr.dep_store', raise_if_not_found=False) else False

                # Collect valid department IDs into a list.
                nilesh_specific_dept_ids = [did for did in [qc_department_id, qa_department_id, store_department_id] if
                                            did]

                # Construct the filter for 'nilesh@rsdpolymers.com' user:
                # They see tasks assigned to them OR tasks where they are the checker
                # OR tasks assigned to users in specific departments.
                if nilesh_specific_dept_ids:  # Apply this specific filter only if the departments are found
                    custom_filter = [
                        '|',  # Main OR: (Personal Tasks for Nilesh) OR (Tasks in specific departments)
                        '|',  # Inner OR for Personal Tasks: (Assigned to Nilesh) OR (Nilesh is Checker)
                        ('user_ids', 'in', current_user.id),  # Task is assigned to the current user
                        ('checker_id', '=', current_user.id),  # Using '=' for direct match with the checker_id field
                        ('user_ids.employee_ids.department_id', 'in', nilesh_specific_dept_ids)
                        # Tasks assigned to users in specific departments
                    ]
                else:
                    # Fallback for 'nilesh@rsdpolymers.com' if specific departments are not found:
                    # They only see tasks assigned to them OR where they are the checker.
                    custom_filter = [
                        '|',
                        ('user_ids', 'in', current_user.id),
                        ('checker_id', '=', current_user.id),  # Using '=' for direct match
                    ]
            else:
                # 3. General Logic for Other Non-Admin Users (who are NOT 'nilesh@rsdpolymers.com'):
                # As per your last instruction, these users only see tasks assigned to them
                # OR where they are the checker, irrespective of their department.
                custom_filter = [
                    '|',  # OR condition
                    ('user_ids', 'in', current_user.id),  # Task is assigned to the current user
                    ('checker_id', '=', current_user.id),  # Using '=' for direct match
                ]

            # Now, combine the determined custom filter with the original domain.
            # If there's a custom filter, it should be logically ANDed with the original domain.
            if custom_filter:
                if original_domain:
                    # If both custom filter and original domain exist, combine them using '&'.
                    final_domain = ['&'] + original_domain + custom_filter
                else:
                    # If only the custom filter exists (meaning the original domain was empty).
                    final_domain = custom_filter
            else:
                # If no custom filter is applied (this case shouldn't be reached for non-admins
                # as custom_filter is always built for them, but included for robustness),
                # the final domain is simply the original domain.
                final_domain = original_domain

        # Reconstruct the *args tuple with the new final domain to pass to the super method.
        # This ensures all original positional and keyword arguments are preserved.
        new_args_tuple = (final_domain,) + args[1:] if args else (final_domain,)
        return super()._search(*new_args_tuple, **kwargs)

