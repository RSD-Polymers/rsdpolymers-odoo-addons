
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class QaChangeControlTask(models.Model):
    _name = 'qa.change.control.task'
    _description = 'Change Control Evaluation Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expected_date, id'

    name = fields.Char(
        string='Task Title',
        required=True,
        tracking=True
    )
    change_control_id = fields.Many2one(
        'qa.change.control',
        string='Change Request',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Assigned Department',
        required=True,
        tracking=True
    )
    assigned_employee_id = fields.Many2one(
        'hr.employee',
        string='Assigned Employee',
        required=True,
        tracking=True
    )
    assigned_user_id = fields.Many2one(
        'res.users',
        related='assigned_employee_id.user_id',
        store=True,
        readonly=True
    )
    expected_date = fields.Date(
        string='Expected Date of Completion',
        required=True,
        tracking=True
    )
    description = fields.Text(required=True)
    completion_comments = fields.Text(tracking=True)
    rework_instructions = fields.Text(string='QA Rework Instructions', readonly=True, tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Task Attachments'
    )
    state = fields.Selection([
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted'),
        ('rework', 'Rework')
    ], default='assigned', required=True, tracking=True, index=True)
    submitted_on = fields.Datetime(readonly=True, tracking=True)

    @api.onchange('assigned_employee_id')
    def _onchange_assigned_employee_id(self):
        """Automatically derive the task department from the selected employee."""
        if self.assigned_employee_id:
            self.department_id = self.assigned_employee_id.department_id
        else:
            self.department_id = False

    # ---------------------------------------------------------
    # VALIDATIONS
    # ---------------------------------------------------------

    @api.constrains('assigned_employee_id', 'department_id')
    def _check_employee_department(self):
        for rec in self:
            if rec.assigned_employee_id.department_id != rec.department_id:
                raise UserError(_(
                    'The assigned employee must belong to the selected department.'
                ))

            if not rec.assigned_employee_id.user_id or rec.assigned_employee_id.user_id.share:
                raise UserError(_(
                    'The assigned employee must be linked to an internal Odoo user.'
                ))

    def _check_qa_user(self):
        user = self.env.user
        if not (
            user.has_group('rsd_qa_management.group_qa_officer')
            or user.has_group('rsd_qa_management.group_qa_manager')
            or user.has_group('base.group_system')
        ):
            raise AccessError(_('Only QA can perform this operation.'))

    def _check_assignee_or_qa(self):
        self.ensure_one()

        if self.assigned_user_id != self.env.user:
            raise UserError(
                _('Only the assigned employee can perform this action.')
            )

    def _check_parent_active(self):
        self.ensure_one()

        if self.change_control_id.state not in ('evaluation', 'data_review'):
            raise UserError(_(
                'Tasks can only be processed during Evaluation or Data Review.'
            ))

    # ---------------------------------------------------------
    # CREATE
    # ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        self._check_qa_user()

        for vals in vals_list:
            if vals.get('assigned_employee_id'):
                employee = self.env['hr.employee'].browse(vals['assigned_employee_id']).exists()
                vals['department_id'] = employee.department_id.id if employee else False

            cr = self.env['qa.change.control'].browse(
                vals.get('change_control_id')
            ).exists()

            if not cr:
                raise UserError(_('Please select a valid Change Request.'))

            if cr.state != 'evaluation':
                raise UserError(_(
                    'Evaluation tasks can only be created during the Evaluation stage.'
                ))

            vals['state'] = 'assigned'
            vals['submitted_on'] = False

        tasks = super().create(vals_list)

        for task in tasks:
            if task.assigned_user_id:
                task.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=task.assigned_user_id.id,
                    date_deadline=task.expected_date,
                    summary=_('Complete Change Control evaluation task'),
                    note=_(
                        'Please complete and submit task: %s'
                    ) % task.name,
                )

        return tasks

    # ---------------------------------------------------------
    # WRITE
    # ---------------------------------------------------------

    def write(self, vals):
        user = self.env.user

        if 'assigned_employee_id' in vals:
            employee = self.env['hr.employee'].browse(vals['assigned_employee_id']).exists()
            vals = dict(vals, department_id=employee.department_id.id if employee else False)

        is_qa = (
            user.has_group('rsd_qa_management.group_qa_officer')
            or user.has_group('rsd_qa_management.group_qa_manager')
            or user.has_group('base.group_system')
        )

        # Task state and submission timestamp are controlled by workflow actions.
        if 'state' in vals or 'submitted_on' in vals:
            raise AccessError(_(
                'Task status and submission date can only be changed using task workflow buttons.'
            ))

        if 'change_control_id' in vals:
            raise AccessError(_(
                'A task cannot be moved to another Change Request after creation.'
            ))

        for rec in self:
            rec._check_parent_active()

            if is_qa:
                if rec.state == 'submitted':
                    raise UserError(_(
                        'This task is already submitted. Request rework before modifying it.'
                    ))
            else:
                if rec.assigned_user_id.id != user.id:
                    raise AccessError(_(
                        'Only the assigned employee can update this task.'
                    ))

                if rec.state == 'submitted':
                    raise UserError(_(
                        'Submitted tasks cannot be modified unless QA requests rework.'
                    ))

                if rec.state not in ('assigned', 'in_progress', 'rework'):
                    raise UserError(_(
                        'This task cannot be modified in its current status.'
                    ))

                allowed_fields = {'completion_comments', 'attachment_ids'}
                if set(vals) - allowed_fields:
                    raise AccessError(_(
                        'Assigned employees can update only completion comments and attachments.'
                    ))

        return super().write(vals)

    def action_open_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Evaluation Task'),
            'res_model': 'qa.change.control.task',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    # ---------------------------------------------------------
    # START TASK
    # ---------------------------------------------------------

    def action_start(self):
        for rec in self:
            rec._check_assignee_or_qa()
            rec._check_parent_active()

            if rec.state not in ('assigned', 'rework'):
                raise UserError(_(
                    'Only assigned or rework tasks can be started.'
                ))

            super(QaChangeControlTask, rec).write({
                'state': 'in_progress'
            })

            rec.message_post(body=_('Task started by %s.') % self.env.user.name)

        return True

    # ---------------------------------------------------------
    # SUBMIT TASK
    # ---------------------------------------------------------

    def action_submit(self):
        for rec in self:
            rec._check_assignee_or_qa()
            rec._check_parent_active()

            if rec.state not in ('assigned', 'in_progress', 'rework'):
                raise UserError(_(
                    'This task has already been submitted.'
                ))

            if not rec.completion_comments or not rec.completion_comments.strip():
                raise UserError(_(
                    'Please enter completion comments before submitting.'
                ))

            super(QaChangeControlTask, rec).write({
                'state': 'submitted',
                'submitted_on': fields.Datetime.now()
            })

            cr = rec.change_control_id

            cr.message_post(
                body=_('Evaluation task "%s" was submitted by %s.') % (
                    rec.name,
                    self.env.user.name
                )
            )

            # First task submission moves the CR to Data Review.
            if cr.state == 'evaluation':
                cr._transition(
                    'data_review',
                    _('First evaluation task submitted. QA Data Review started.')
                )

                cr._notify_qa(_(
                    'An evaluation task for %s has been submitted. '
                    'Data Review is now required.'
                ) % cr.name)

            # Remaining tasks can still be submitted in Data Review.
            elif cr.state == 'data_review':
                cr._notify_qa(_(
                    'Another evaluation task for %s has been submitted.'
                ) % cr.name)

        return True

    # ---------------------------------------------------------
    # REQUEST REWORK
    # ---------------------------------------------------------

    def action_request_rework(self):
        self.ensure_one()
        self._check_qa_user()
        self._check_parent_active()

        if self.change_control_id.state != 'data_review':
            raise UserError(_(
                'Task rework can only be requested during Data Review.'
            ))

        if self.state != 'submitted':
            raise UserError(_(
                'Only submitted tasks can be sent for rework.'
            ))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Request Task Rework'),
            'res_model': 'qa.change.control.task.rework.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }

    def _apply_rework_request(self, instructions):
        self.ensure_one()
        self._check_qa_user()
        self._check_parent_active()

        if self.change_control_id.state != 'data_review' or self.state != 'submitted':
            raise UserError(_(
                'Only submitted tasks in Data Review can be sent for rework.'
            ))
        if not instructions or not instructions.strip():
            raise UserError(_('Please enter the rework instructions.'))

        # Apply the controlled workflow update, bypassing the normal task write guard.
        super(QaChangeControlTask, self).write({
            'state': 'rework',
            'submitted_on': False,
            'rework_instructions': instructions.strip(),
        })

        message = _(
            'QA requested rework for task "%s". Instructions: %s'
        ) % (self.name, instructions.strip())
        self.change_control_id.message_post(body=message)
        self.message_post(body=_('QA requested rework: %s') % instructions.strip())

        if self.assigned_user_id:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=self.assigned_user_id.id,
                summary=_('Change Control task rework required'),
                note=_(
                    'QA has requested rework for task "%s".\n\nInstructions: %s\n\nPlease review the instructions and resubmit.'
                ) % (self.name, instructions.strip())
            )
        return True

    # ---------------------------------------------------------
    # DEADLINE REMINDERS
    # ---------------------------------------------------------

    @api.model
    def _cron_notify_tasks_due_tomorrow(self):
        tomorrow = fields.Date.add(
            fields.Date.context_today(self),
            days=1
        )

        tasks = self.search([
            ('expected_date', '=', tomorrow),
            ('state', '!=', 'submitted'),
            ('change_control_id.state', 'in', ['evaluation', 'data_review']),
        ])

        qa_users = (
            self.env.ref('rsd_qa_management.group_qa_officer').users
            | self.env.ref('rsd_qa_management.group_qa_manager').users
        )

        model_id = self.env['ir.model']._get_id(self._name)

        for task in tasks:
            recipients = qa_users

            if task.assigned_user_id:
                recipients |= task.assigned_user_id

            for user in recipients:
                exists = self.env['mail.activity'].search_count([
                    ('res_model_id', '=', model_id),
                    ('res_id', '=', task.id),
                    ('user_id', '=', user.id),
                    ('summary', '=', _('Task deadline tomorrow')),
                ])

                if not exists:
                    task.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=user.id,
                        date_deadline=fields.Date.context_today(self),
                        summary=_('Task deadline tomorrow'),
                        note=_(
                            'Task "%s" under Change Request "%s" '
                            'is due tomorrow. Please follow up.'
                        ) % (
                            task.name,
                            task.change_control_id.name
                        ),
                    )

        return True
