from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class QaChangeControl(models.Model):
    _name = 'qa.change.control'
    _description = 'QA Change Control'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='CR Number', required=True, copy=False, readonly=True, default='New', tracking=True)
    description = fields.Text(required=True, tracking=True)
    requested_by_id = fields.Many2one('hr.employee', string='Change Request By', required=True, default=lambda self: self._default_employee(), tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='requested_by_id.department_id', store=True, readonly=True)
    request_date = fields.Date(string='Request Date', default=fields.Date.context_today, readonly=True)
    cr_type = fields.Selection([
        ('sop_process', 'SOP or Process'),
        ('forms_formats', 'Forms & Formats'),
        ('records', 'Records'),
        ('other', 'Other'),
    ], string='CR Type', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('registered', 'Registered'),
        ('evaluation', 'Evaluation'),
        ('data_review', 'Data Review'),
        ('approval_pending', 'Awaiting AB Approval'),
        ('closing_report', 'Closing Report'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True, index=True, copy=False)
    task_ids = fields.One2many('qa.change.control.task', 'change_control_id', string='Evaluation Tasks')
    task_count = fields.Integer(compute='_compute_task_count')
    submitted_task_count = fields.Integer(compute='_compute_task_count')
    pending_task_count = fields.Integer(compute='_compute_task_count')
    rejection_reason = fields.Text(readonly=True, tracking=True)
    qa_reviewer_id = fields.Many2one('res.users', string='QA Reviewer', default=lambda self: self._default_qa_reviewer(), tracking=True)
    approval_ids = fields.One2many('qa.change.control.approval', 'change_control_id', string='Approval History')
    ab_approver_id = fields.Many2one('res.users', string='AB Approver', tracking=True, domain=[('share', '=', False)])
    approval_comment = fields.Text(readonly=True, tracking=True)
    document_ids = fields.One2many('qa.change.control.document', 'change_control_id', string='Review Documents')
    review_comments = fields.Text(string='QA Review Comments', tracking=True)
    implementation_details = fields.Text(string='Implementation Details', tracking=True)
    implementation_date = fields.Date(string='Implementation Date', tracking=True)
    closing_report_attachment_ids = fields.Many2many(
        'ir.attachment', 'qa_change_control_closing_attachment_rel', 'change_control_id', 'attachment_id',
        string='Post-Implementation Report'
    )
    final_comments = fields.Text(string='Final Comments', tracking=True)
    completed_by_id = fields.Many2one('hr.employee', string='Completed By', readonly=True)
    completion_date = fields.Date(string='Completion Date', readonly=True)
    is_task_submission_complete = fields.Boolean(compute='_compute_task_count')

    @api.model
    def _default_employee(self):
        return self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)

    @api.model
    def _default_qa_reviewer(self):
        if (self.env.user.has_group('rsd_qa_management.group_qa_officer') or
                self.env.user.has_group('rsd_qa_management.group_qa_manager') or
                self.env.user.has_group('base.group_system')):
            return self.env.uid
        return False

    @api.depends('task_ids', 'task_ids.state')
    def _compute_task_count(self):
        for rec in self:
            rec.task_count = len(rec.task_ids)
            rec.submitted_task_count = len(rec.task_ids.filtered(lambda t: t.state == 'submitted'))
            rec.pending_task_count = rec.task_count - rec.submitted_task_count
            rec.is_task_submission_complete = bool(rec.task_count) and rec.pending_task_count == 0

    @api.model_create_multi
    def create(self, vals_list):
        user = self.env.user
        is_qa = (
            user.has_group('rsd_qa_management.group_qa_officer')
            or user.has_group('rsd_qa_management.group_qa_manager')
            or user.has_group('base.group_system')
        )

        allowed_create_fields = {
            'name',
            'description',
            'requested_by_id',
            'cr_type',
            'qa_reviewer_id',
            'request_date',
            'state',
        }

        for vals in vals_list:
            extra_fields = set(vals) - allowed_create_fields
            if extra_fields:
                raise AccessError(_(
                    'These fields cannot be set when creating a Change Request: %s'
                ) % ', '.join(sorted(extra_fields)))

            if not is_qa:
                employee = self.env['hr.employee'].search(
                    [('user_id', '=', user.id)], limit=1
                )
                if not employee:
                    raise UserError(_(
                        'Your user is not linked to an employee. Please contact HR.'
                    ))
                vals['requested_by_id'] = employee.id
                vals.pop('qa_reviewer_id', None)
            vals['state'] = 'draft'

            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'qa.change.control'
                ) or 'New'

        return super().create(vals_list)

    def write(self, vals):
        user = self.env.user

        # All stage changes must pass through the validated workflow actions.
        if 'state' in vals:
            raise AccessError(_(
                'Change Request stages can only be changed using workflow buttons.'
            ))

        is_qa = (
            user.has_group('rsd_qa_management.group_qa_officer')
            or user.has_group('rsd_qa_management.group_qa_manager')
            or user.has_group('base.group_system')
        )

        if not is_qa:
            for rec in self:
                if (
                    rec.state != 'draft'
                    or rec.requested_by_id.user_id.id != user.id
                ):
                    raise AccessError(_(
                        'Only QA can modify a submitted Change Request.'
                    ))

                if set(vals) - {'cr_type', 'description'}:
                    raise AccessError(_(
                        'In Draft, employees can edit only CR Type and Description.'
                    ))
        else:
            allowed_fields_by_state = {
                'draft': {
                    'requested_by_id',
                    'cr_type',
                    'description',
                    'qa_reviewer_id',
                },
                'open': {
                    'rejection_reason',
                    'qa_reviewer_id',
                },
                'registered': {
                    'qa_reviewer_id',
                },
                'evaluation': {
                    'qa_reviewer_id',
                    'ab_approver_id',
                },
                'data_review': {
                    'qa_reviewer_id',
                    'ab_approver_id',
                    'review_comments',
                },
                'approval_pending': set(),
                'closing_report': {
                    'implementation_details',
                    'implementation_date',
                    'closing_report_attachment_ids',
                    'final_comments',
                },
                'completed': set(),
                'rejected': set(),
            }

            for rec in self:
                allowed_fields = allowed_fields_by_state.get(rec.state, set())
                restricted_fields = set(vals) - allowed_fields
                if restricted_fields:
                    raise AccessError(_(
                        'You cannot modify these fields in the current stage: %s'
                    ) % ', '.join(sorted(restricted_fields)))

        return super().write(vals)

    def _transition(self, state, message=None):
        # Bypass the public write guard only from this private, validated workflow helper.
        super(QaChangeControl, self).write({'state': state})
        if message:
            self.message_post(body=message)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft requests can be submitted.'))
            if not (rec.requested_by_id.user_id.id == self.env.uid or self.env.user.has_group('base.group_system')):
                raise AccessError(_('Only the requester can submit this Change Request.'))
            rec._transition('open', _('Change Request submitted to QA.'))
            rec._notify_qa(_('New Change Request %s requires registration.') % rec.name)
        return True

    def action_register(self):
        self._check_qa_user()
        for rec in self:
            if rec.state != 'open':
                raise UserError(_('Only Open requests can be registered.'))
            rec._transition('registered', _('Change Request registered by QA.'))
        return True

    def action_reject(self):
        self._check_qa_user()
        self.ensure_one()
        if self.state != 'open':
            raise UserError(_('Only Open requests can be rejected.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('Reject Change Request'),
            'res_model': 'qa.change.control.reject.wizard', 'view_mode': 'form',
            'target': 'new', 'context': {'default_change_control_id': self.id},
        }

    def action_start_evaluation(self):
        self._check_qa_user()
        for rec in self:
            if rec.state != 'registered':
                raise UserError(_('Only Registered requests can enter Evaluation.'))
            rec._transition('evaluation', _('Evaluation started by QA.'))
        return True

    def action_send_for_approval(self):
        self._check_qa_user()
        for rec in self:
            if rec.state != 'data_review':
                raise UserError(_('The request must be in Data Review.'))
            if not rec.task_ids:
                raise UserError(_('At least one evaluation task is required.'))
            if rec.task_ids.filtered(lambda t: t.state != 'submitted'):
                raise UserError(_('All evaluation tasks must be submitted before sending for approval.'))
            if not rec.ab_approver_id:
                raise UserError(_('Please select the AB Approver before sending for approval.'))
            rec._transition('approval_pending', _('QA sent the Change Request for AB approval.'))
            rec.env['qa.change.control.approval'].create({
                'change_control_id': rec.id,
                'approver_id': rec.ab_approver_id.id,
                'requested_by_id': self.env.user.id,
                'requested_on': fields.Datetime.now(),
                'decision': 'pending',
            })
            rec.activity_schedule('mail.mail_activity_data_todo', user_id=rec.ab_approver_id.id,
                                  summary=_('Change Request approval required'),
                                  note=_('Please review and approve/refuse %s.') % rec.name)
            rec.message_post(body=_('Approval requested from %s.') % rec.ab_approver_id.name)
        return True

    def _get_pending_approval(self):
        self.ensure_one()
        pending_approvals = self.approval_ids.filtered(
            lambda approval: approval.decision == 'pending'
        )

        if len(pending_approvals) != 1:
            raise UserError(_(
                'Exactly one pending approval-history record is required before making a decision.'
            ))

        approval = pending_approvals[0]
        if approval.approver_id != self.ab_approver_id:
            raise UserError(_(
                'The pending approval record does not match the selected Approver.'
            ))

        return approval

    def action_ab_approve(self):
        self.ensure_one()
        self._check_ab_user()

        if self.state != 'approval_pending':
            raise UserError(_('This request is not awaiting AB approval.'))

        pending_approval = self._get_pending_approval()
        pending_approval.sudo().write({
            'decision': 'approved',
            'decision_date': fields.Datetime.now(),
            'comment': _('Approved by %s') % self.env.user.name,
        })

        self._transition(
            'closing_report',
            _('Change Request approved by %s.') % self.env.user.name
        )
        self._notify_qa(_(
            'Change Request %s was approved and is ready for Closing Report.'
        ) % self.name)
        return True

    def action_ab_refuse(self):
        self.ensure_one()
        self._check_ab_user()

        if self.state != 'approval_pending':
            raise UserError(_('This request is not awaiting AB approval.'))

        # Confirm the approval history is valid before opening the refusal wizard.
        self._get_pending_approval()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refuse Change Request'),
            'res_model': 'qa.change.control.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_change_control_id': self.id},
        }

    def _record_ab_refusal(self, reason):
        self.ensure_one()
        self._check_ab_user()

        if self.state != 'approval_pending':
            raise UserError(_('This request is not awaiting AB approval.'))
        if not reason or not reason.strip():
            raise UserError(_('Please provide a reason for refusing the request.'))

        pending_approval = self._get_pending_approval()
        reason = reason.strip()

        super(QaChangeControl, self).write({'approval_comment': reason})
        pending_approval.sudo().write({
            'decision': 'refused',
            'decision_date': fields.Datetime.now(),
            'comment': reason,
        })
        self._transition(
            'evaluation',
            _('AB refused the Change Request. Returned to Evaluation. Reason: %s') % reason
        )
        self._notify_qa(_(
            'AB refused %s. Please review and rework the evaluation.'
        ) % self.name)
        return True

    def action_mark_done(self):
        self._check_qa_user()
        for rec in self:
            if rec.state != 'closing_report':
                raise UserError(_('Only requests in Closing Report can be completed.'))
            if not rec.implementation_details or not rec.implementation_date or not rec.closing_report_attachment_ids:
                raise UserError(_('Implementation details, implementation date and post-implementation report are required.'))
            employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
            super(QaChangeControl, rec).write({
                'completed_by_id': employee.id,
                'completion_date': fields.Date.context_today(self),
            })
            rec._transition('completed', _('Post-Implementation Report submitted. Change Request completed.'))
        return True

    def action_view_tasks(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Evaluation Tasks'),
                'res_model': 'qa.change.control.task', 'view_mode': 'list,form',
                'domain': [('change_control_id', '=', self.id)],
                'context': {'default_change_control_id': self.id}}

    def _check_qa_user(self):
        if not (self.env.user.has_group('rsd_qa_management.group_qa_officer') or
                self.env.user.has_group('rsd_qa_management.group_qa_manager') or
                self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only QA Officers, QA Managers or Administrators can perform this action.'))

    def _check_ab_user(self):
        self.ensure_one()

        if self.ab_approver_id != self.env.user:
            raise UserError(
                _('Only the assigned Approver can approve or refuse this request.')
            )

    def _notify_qa(self, message):
        group = self.env.ref('rsd_qa_management.group_qa_officer')
        users = group.users | self.env.ref('rsd_qa_management.group_qa_manager').users
        for user in users:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                   summary=_('Change Control notification'), note=message)

    def action_open_pending(self):
        return {'type': 'ir.actions.act_window', 'name': _('Pending Change Requests'),
                'res_model': 'qa.change.control', 'view_mode': 'list,kanban,form',
                'domain': [('state', 'not in', ['completed', 'rejected'])]}

    @api.model
    def get_dashboard_data(self):
        total = self.search_count([])
        completed = self.search_count([('state', '=', 'completed')])
        pending = self.search_count([('state', 'not in', ['completed', 'rejected'])])
        stages = []
        for key, label in self._fields['state'].selection:
            count = self.search_count([('state', '=', key)])
            stages.append({'key': key, 'label': label, 'count': count})
        return {'total': total, 'completed': completed, 'pending': pending,
                'completion_rate': round((completed / total) * 100, 1) if total else 0,
                'stages': stages}


class QaChangeControlDocument(models.Model):
    _name = 'qa.change.control.document'
    _description = 'Change Control Review Document'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    change_control_id = fields.Many2one('qa.change.control', required=True, ondelete='cascade', index=True)
    document_type = fields.Selection([('evaluation', 'Evaluation Evidence'), ('revised', 'Revised Document'), ('other', 'Other')], default='evaluation', required=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments', required=True)
    uploaded_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            cr = self.env['qa.change.control'].browse(
                vals.get('change_control_id')
            ).exists()
            if not cr:
                raise UserError(_('Please select a valid Change Request.'))

            cr._check_qa_user()
            if cr.state != 'data_review':
                raise UserError(_(
                    'Review documents can only be added during Data Review.'
                ))

            # The uploader is always the logged-in user.
            vals['uploaded_by_id'] = self.env.uid

        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {'change_control_id', 'uploaded_by_id'}
        if protected_fields.intersection(vals):
            raise AccessError(_(
                'The related Change Request and uploader cannot be changed after document creation.'
            ))

        for document in self:
            document.change_control_id._check_qa_user()
            if document.change_control_id.state != 'data_review':
                raise UserError(_(
                    'Documents can only be modified during Data Review.'
                ))

        return super().write(vals)



class QaChangeControlApproval(models.Model):
    _name = 'qa.change.control.approval'
    _description = 'Change Control Approval History'
    _order = 'requested_on desc, id desc'

    change_control_id = fields.Many2one('qa.change.control', required=True, ondelete='cascade', index=True)
    approver_id = fields.Many2one('res.users', string='AB Approver', required=True)
    requested_by_id = fields.Many2one('res.users', string='Sent By', required=True)
    requested_on = fields.Datetime(required=True)
    decision = fields.Selection([('pending', 'Pending'), ('approved', 'Approved'), ('refused', 'Refused')], required=True, default='pending')
    decision_date = fields.Datetime()
    comment = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            cr = self.env['qa.change.control'].browse(
                vals.get('change_control_id')
            ).exists()
            if not cr:
                raise UserError(_('Please select a valid Change Request.'))

            cr._check_qa_user()
            if cr.state != 'approval_pending':
                raise UserError(_(
                    'Approval history can only be created when the request is awaiting approval.'
                ))
            if vals.get('approver_id') != cr.ab_approver_id.id:
                raise ValidationError(_(
                    'The approval-history Approver must match the selected Change Request Approver.'
                ))
            if vals.get('requested_by_id') != self.env.uid:
                raise AccessError(_(
                    'The approval request must be recorded under the logged-in QA user.'
                ))
            if vals.get('decision', 'pending') != 'pending':
                raise ValidationError(_(
                    'A new approval-history record must start with Pending decision.'
                ))
            if cr.approval_ids.filtered(lambda approval: approval.decision == 'pending'):
                raise ValidationError(_(
                    'A pending approval-history record already exists for this request.'
                ))

            vals['requested_on'] = fields.Datetime.now()
            vals['decision'] = 'pending'
            vals['decision_date'] = False
            vals['comment'] = False

        return super().create(vals_list)
