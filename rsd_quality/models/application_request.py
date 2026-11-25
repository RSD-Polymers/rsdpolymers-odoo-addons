from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

PARAMETERS = [
    ('inhibition', 'Inhibition'), ('ard', 'ARD'), ('desperation', 'Desperation'),
    ('soil_stain', 'Soil Stain Removal'), ('adw', 'ADW'), ('other', 'Any Other'),
]
OWNER_GROUP = 'rnd_workflow.group_rnd_owner'
REQUESTER_GROUP = 'rnd_workflow.group_rnd_sm'
TESTER_GROUP = 'rsd_quality.group_application_test_user'
SYSTEM_GROUP = 'base.group_system'


def _is_manager(user):
    return user.has_group(OWNER_GROUP) or user.has_group(SYSTEM_GROUP)


class RSDApplicationRequest(models.Model):
    _name = 'rsd.quality.application.request'
    _description = 'R&D Application Test Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False, tracking=True)
    requester_id = fields.Many2one('res.users', string='Request Owner / Original Requester', default=lambda self: self.env.user, readonly=True, required=True, tracking=True)
    requester_employee_id = fields.Many2one('hr.employee', related='requester_id.employee_id', store=True)
    department_id = fields.Many2one('hr.department', related='requester_employee_id.department_id', store=True)
    designation = fields.Char(related='requester_employee_id.job_title', store=True)
    request_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    sample_name = fields.Char(required=True, tracking=True)
    batch_no = fields.Char(string='Batch No.', tracking=True)
    quantity = fields.Float(required=True, tracking=True)
    quantity_uom = fields.Many2one('uom.uom', string='Unit', default=lambda self: self.env.ref('uom.product_uom_kgm', raise_if_not_found=False))
    manufacturer_name = fields.Char()
    sender_name = fields.Char(required=True)
    purpose = fields.Text(required=True)
    coa_attachment_ids = fields.Many2many('ir.attachment', string='COA Attachments')
    sent_by = fields.Char(required=True)
    delivery_mode = fields.Selection([('courier', 'Courier'), ('hand', 'Hand Delivery'), ('transport', 'Transport'), ('other', 'Other')], required=True)
    compare_performance = fields.Text(string='Compare Performance With')
    parameter_ids = fields.Many2many(
        'rsd.quality.application.parameter',
        relation='rsd_app_request_parameter_rel',
        column1='request_id',
        column2='parameter_id',
        string='Performance Test Parameters',
        required=True,
    )
    other_parameter = fields.Char(string='Other Parameter')
    has_other_parameter = fields.Boolean(compute='_compute_has_other_parameter')

    @api.depends('parameter_ids.code')
    def _compute_has_other_parameter(self):
        for rec in self:
            rec.has_other_parameter = 'other' in rec.parameter_ids.mapped('code')
    inhibition_test_ids = fields.Many2many('rsd.quality.inhibition.test', string='Inhibition Tests')
    inhibition_snapshot = fields.Text(readonly=True)
    assigned_user_id = fields.Many2one('res.users', string='Application User', tracking=True)
    sample_received_date = fields.Date(tracking=True)
    feasibility = fields.Selection([('yes', 'Feasible'), ('no', 'Not Feasible')], tracking=True)
    feasibility_reason = fields.Text()
    proposed_completion_date = fields.Date(tracking=True)
    date_feedback = fields.Text()
    date_proposal_history = fields.Text(readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('sample_received', 'Sample Received'),
        ('feasibility_pending', 'Feasibility Pending'), ('infeasible', 'Not Feasible'),
        ('date_acceptance', 'Expected Date Approval'), ('date_revision', 'Expected Date Revision'),
        ('testing', 'Testing In Progress'), ('review', 'Awaiting Requester Review'),
        ('completed', 'Completed'), ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    attempt_ids = fields.One2many('rsd.quality.application.attempt', 'request_id', string='Testing Attempts')
    current_attempt_id = fields.Many2one('rsd.quality.application.attempt', compute='_compute_current_attempt')
    attempt_count = fields.Integer(compute='_compute_current_attempt')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    @api.depends('attempt_ids.attempt_no')
    def _compute_current_attempt(self):
        for rec in self:
            attempts = rec.attempt_ids.sorted('attempt_no')
            rec.attempt_count = len(attempts)
            rec.current_attempt_id = attempts[-1] if attempts else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['requester_id'] = self.env.uid
            vals['state'] = 'draft'
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rsd.quality.application.request') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        protected = {'requester_id', 'name', 'state', 'attempt_ids', 'current_attempt_id', 'attempt_count',
                     'date_proposal_history', 'sample_received_date', 'feasibility', 'feasibility_reason',
                     'proposed_completion_date', 'date_feedback', 'inhibition_snapshot'}
        if protected.intersection(vals):
            raise UserError(_('Workflow and ownership fields must be changed through workflow actions.'))
        for rec in self:
            if rec.state not in ('draft', 'infeasible') and vals:
                raise UserError(_('Request details are locked after submission.'))
            if rec.requester_id != self.env.user and not _is_manager(self.env.user):
                raise UserError(_('Only the original requester or R&D Manager may edit request details.'))
        return super().write(vals)

    def _require_requester(self):
        if any(r.requester_id != self.env.user for r in self) and not _is_manager(self.env.user):
            raise UserError(_('Only the original requester or an R&D Manager can perform this action.'))

    def _require_assigned_tester(self):
        if not self.env.user.has_group(TESTER_GROUP) and not _is_manager(self.env.user):
            raise UserError(_('You do not have Application Testing access.'))
        if any(r.assigned_user_id != self.env.user for r in self) and not _is_manager(self.env.user):
            raise UserError(_('Only the assigned Application User can perform this action.'))

    def _wf(self, vals):
        # Called only after workflow methods validate state and actor.
        return super(RSDApplicationRequest, self.sudo()).write(vals)

    def action_submit_request(self):
        self._require_requester()
        for rec in self:
            if rec.state not in ('draft', 'infeasible'):
                raise UserError(_('Only Draft or Not Feasible requests can be submitted.'))
            if not rec.assigned_user_id or not rec.parameter_ids:
                raise ValidationError(_('Assign an Application User and select at least one test parameter.'))
            if 'other' in rec.parameter_ids.mapped('code') and not rec.other_parameter:
                raise ValidationError(_('Specify the Other parameter.'))
            snapshot = '\n'.join('%s: %s' % (t.name, t.conditions) for t in rec.inhibition_test_ids) or False
            rec._wf({'state': 'submitted', 'feasibility': False, 'feasibility_reason': False, 'inhibition_snapshot': snapshot})
            rec.message_post(body=_('Application test request submitted.'))
            rec._notify(rec.assigned_user_id, _('Application Testing Request Assigned'), _('A new request %s has been assigned to you.') % rec.name)
        return True

    def action_sample_received(self):
        self.ensure_one()
        self._require_assigned_tester()
        if self.state != 'submitted':
            raise UserError(_('Sample acknowledgement is available only for submitted requests.'))
        return self._wizard('rsd.quality.application.sample.received.wizard')

    def action_feasibility(self):
        self.ensure_one()
        self._require_assigned_tester()
        if self.state not in ('sample_received', 'feasibility_pending', 'date_revision'):
            raise UserError(_('Feasibility is available after sample receipt or when a date revision is requested.'))
        return self._wizard('rsd.quality.application.feasibility.wizard')

    def action_date_review(self):
        self.ensure_one()
        self._require_requester()
        if self.state != 'date_acceptance':
            raise UserError(_('No expected date is awaiting review.'))
        return self._wizard('rsd.quality.application.date.review.wizard')

    def action_submit_attempt(self):
        self.ensure_one()
        self._require_assigned_tester()
        if self.state != 'testing' or not self.current_attempt_id:
            raise UserError(_('There is no active attempt available to submit.'))
        return self.current_attempt_id.action_submit()

    def action_attempt_review(self):
        self.ensure_one()
        self._require_requester()
        if self.state != 'review':
            raise UserError(_('No attempt is awaiting review.'))
        return self._wizard('rsd.quality.application.attempt.review.wizard')

    def action_cancel_request(self):
        self.ensure_one()
        self._require_requester()
        if self.state not in ('draft', 'submitted', 'infeasible'):
            raise UserError(_('This request cannot be cancelled at this stage.'))
        self._wf({'state': 'cancelled'})
        return True

    def _wizard(self, model):
        ctx = dict(self.env.context, default_request_id=self.id)
        if model == 'rsd.quality.application.feasibility.wizard' and self.state == 'date_revision':
            ctx['default_feasibility'] = 'yes'
        return {'type': 'ir.actions.act_window', 'name': _('Workflow Action'), 'res_model': model,
                'view_mode': 'form', 'target': 'new', 'context': ctx}

    def _notify(self, user, title, body):
        if user:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=title, note=body)
            self.message_post(body=body, partner_ids=user.partner_id.ids)


class RSDApplicationParameter(models.Model):
    _name = 'rsd.quality.application.parameter'
    _description = 'Application Test Parameter'
    _order = 'sequence,name'
    name = fields.Char(required=True)
    code = fields.Selection(PARAMETERS, required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class RSDInhibitionTest(models.Model):
    _name = 'rsd.quality.inhibition.test'
    _description = 'Inhibition Test Condition'
    _order = 'sequence,name'
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    conditions = fields.Text(required=True)
    active = fields.Boolean(default=True)


class RSDApplicationAttempt(models.Model):
    _name = 'rsd.quality.application.attempt'
    _description = 'Application Test Attempt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'attempt_no'

    request_id = fields.Many2one('rsd.quality.application.request', required=True, ondelete='cascade', index=True)
    attempt_no = fields.Integer(required=True, readonly=True)
    name = fields.Char(compute='_compute_name', store=True)
    assigned_user_id = fields.Many2one('res.users', related='request_id.assigned_user_id', store=True)
    state = fields.Selection([('in_progress', 'In Progress'), ('submitted', 'Submitted for Review'),
                             ('revision_requested', 'Revision Requested'), ('accepted', 'Accepted')],
                            default='in_progress', required=True, tracking=True)
    start_date = fields.Date(default=fields.Date.context_today)
    description = fields.Text(string='Test Report / Results', tracking=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Report Attachments')
    submitted_by = fields.Many2one('res.users', readonly=True)
    submitted_on = fields.Datetime(readonly=True)
    requester_feedback = fields.Text(readonly=True, tracking=True)
    reviewed_by = fields.Many2one('res.users', readonly=True)
    reviewed_on = fields.Datetime(readonly=True)

    _sql_constraints = [('request_attempt_unique', 'unique(request_id, attempt_no)', 'Attempt number must be unique per request.')]

    @api.model_create_multi
    def create(self, vals_list):
        # Attempts may only be created through privileged, validated workflow actions.
        if not self.env.su:
            raise UserError(_('Attempts are created only by the request workflow.'))
        for vals in vals_list:
            request = self.env['rsd.quality.application.request'].browse(vals.get('request_id')).exists()
            if not request or request.state not in ('testing', 'date_acceptance', 'review'):
                raise UserError(_('An attempt cannot be created for this request at its current stage.'))
            vals.setdefault('state', 'in_progress')
            if vals.get('state') != 'in_progress':
                raise UserError(_('New attempts must start In Progress.'))
            expected = (request.attempt_count or 0) + 1
            if vals.get('attempt_no') != expected:
                raise UserError(_('Attempt number is not the next valid attempt number.'))
        return super().create(vals_list)

    @api.depends('request_id.name', 'attempt_no')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s - Attempt %s' % (rec.request_id.name, rec.attempt_no)

    def _wf(self, vals):
        # Privileged write only from validated workflow actions below.
        return super(RSDApplicationAttempt, self.sudo()).write(vals)

    def write(self, vals):
        protected = {'state', 'attempt_no', 'submitted_by', 'submitted_on', 'reviewed_by', 'reviewed_on',
                     'requester_feedback', 'request_id'}
        if protected.intersection(vals):
            raise UserError(_('Attempt workflow fields are controlled by workflow actions.'))
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('Submitted or reviewed attempts are locked.'))
            if rec.assigned_user_id != self.env.user and not _is_manager(self.env.user):
                raise UserError(_('Only the assigned Application User may edit this attempt.'))
        return super().write(vals)

    def action_submit(self):
        self.ensure_one()
        req = self.request_id
        req._require_assigned_tester()
        if req.state != 'testing' or req.current_attempt_id != self or self.state != 'in_progress':
            raise UserError(_('Only the active in-progress attempt can be submitted.'))
        if not self.description:
            raise ValidationError(_('Enter test report/results before submitting.'))
        self._wf({'state': 'submitted', 'submitted_by': self.env.uid, 'submitted_on': fields.Datetime.now()})
        req._wf({'state': 'review'})
        req._notify(req.requester_id, _('Attempt Submitted for Review'), _('%s submitted Attempt %s.') % (req.name, self.attempt_no))
        self.message_post(body=_('Submitted for Original Requester review.'))
        return True


class RSDApplicationWizardBase(models.TransientModel):
    _name = 'rsd.quality.application.wizard.base'
    _abstract = True
    request_id = fields.Many2one('rsd.quality.application.request', required=True)


class SampleReceivedWizard(models.TransientModel):
    _name = 'rsd.quality.application.sample.received.wizard'
    _inherit = 'rsd.quality.application.wizard.base'
    _description = 'Sample Received Wizard'
    received_date = fields.Date(default=fields.Date.context_today, required=True)

    def action_confirm(self):
        self.ensure_one()
        r = self.request_id
        r._require_assigned_tester()
        if r.state != 'submitted':
            raise UserError(_('Only a submitted request can be acknowledged.'))
        r._wf({'sample_received_date': self.received_date, 'state': 'sample_received'})
        r.message_post(body=_('Sample received on %s') % self.received_date)
        r._notify(r.requester_id, _('Sample Received'), _('Your sample was received.'))
        return {'type': 'ir.actions.act_window_close'}


class FeasibilityWizard(models.TransientModel):
    _name = 'rsd.quality.application.feasibility.wizard'
    _inherit = 'rsd.quality.application.wizard.base'
    _description = 'Feasibility Wizard'
    feasibility = fields.Selection([('yes', 'Yes'), ('no', 'No')], required=True)
    expected_date = fields.Date()
    reason = fields.Text()

    def action_confirm(self):
        self.ensure_one()
        r = self.request_id
        r._require_assigned_tester()
        if r.state not in ('sample_received', 'feasibility_pending', 'date_revision'):
            raise UserError(_('This request is not awaiting feasibility or a date revision.'))
        if r.state == 'date_revision' and self.feasibility != 'yes':
            raise ValidationError(_('A revised expected date must be proposed.'))
        if self.feasibility == 'yes' and not self.expected_date:
            raise ValidationError(_('Expected completion date is required.'))
        if self.feasibility == 'no' and not self.reason:
            raise ValidationError(_('Reason is mandatory when infeasible.'))
        if self.feasibility == 'no':
            r._wf({'feasibility': 'no', 'feasibility_reason': self.reason, 'state': 'infeasible'})
            r._notify(r.requester_id, _('Request Not Feasible'), self.reason)
        else:
            proposal_label = 'Revised proposal: ' if r.state == 'date_revision' else 'Proposal: '
            history = (r.date_proposal_history or '') + '\n' + proposal_label + str(self.expected_date)
            r._wf({'feasibility': 'yes', 'proposed_completion_date': self.expected_date,
                    'state': 'date_acceptance', 'date_proposal_history': history, 'date_feedback': False})
            r._notify(r.requester_id, _('Expected Completion Date Approval'), _('Proposed completion date: %s') % self.expected_date)
        return {'type': 'ir.actions.act_window_close'}


class DateReviewWizard(models.TransientModel):
    _name = 'rsd.quality.application.date.review.wizard'
    _inherit = 'rsd.quality.application.wizard.base'
    _description = 'Expected Date Review Wizard'
    decision = fields.Selection([('accept', 'Accept'), ('reject', 'Reject')], required=True)
    feedback = fields.Text()

    def action_confirm(self):
        self.ensure_one()
        r = self.request_id
        r._require_requester()
        if r.state != 'date_acceptance':
            raise UserError(_('This request is not awaiting expected-date review.'))
        if self.decision == 'reject' and not self.feedback:
            raise ValidationError(_('Feedback is mandatory when rejecting the proposed date.'))
        if self.decision == 'accept':
            r._wf({'state': 'testing', 'date_feedback': self.feedback or False})
            if not r.attempt_ids:
                self.env['rsd.quality.application.attempt'].sudo().create({'request_id': r.id, 'attempt_no': 1})
            r._notify(r.assigned_user_id, _('Date Approved - Testing Starts'), _('The completion date was accepted. Begin testing.'))
        else:
            history = (r.date_proposal_history or '') + '\nRejected proposal: ' + str(r.proposed_completion_date) + ' | Feedback: ' + self.feedback
            r._wf({'date_feedback': self.feedback, 'date_proposal_history': history, 'state': 'date_revision'})
            r._notify(r.assigned_user_id, _('Expected Date Rejected'), _('Please submit a revised expected completion date. Feedback: %s') % self.feedback)
        return {'type': 'ir.actions.act_window_close'}


class AttemptReviewWizard(models.TransientModel):
    _name = 'rsd.quality.application.attempt.review.wizard'
    _inherit = 'rsd.quality.application.wizard.base'
    _description = 'Attempt Review Wizard'
    decision = fields.Selection([('complete', 'Complete Request'), ('another', 'Request Another Attempt')], required=True)
    feedback = fields.Text()

    def action_confirm(self):
        self.ensure_one()
        r = self.request_id
        r._require_requester()
        a = r.current_attempt_id
        if r.state != 'review' or not a or a.state != 'submitted':
            raise UserError(_('The current submitted attempt is not awaiting review.'))
        if self.decision == 'another' and not self.feedback:
            raise ValidationError(_('Feedback/instructions are mandatory.'))
        if self.decision == 'complete':
            a._wf({'state': 'accepted', 'reviewed_by': self.env.uid, 'reviewed_on': fields.Datetime.now()})
            r._wf({'state': 'completed'})
            r._notify(r.assigned_user_id, _('Request Completed'), _('%s has been completed.') % r.name)
        else:
            a._wf({'state': 'revision_requested', 'requester_feedback': self.feedback,
                   'reviewed_by': self.env.uid, 'reviewed_on': fields.Datetime.now()})
            next_no = a.attempt_no + 1
            self.env['rsd.quality.application.attempt'].sudo().create({'request_id': r.id, 'attempt_no': next_no})
            r._wf({'state': 'testing'})
            r._notify(r.assigned_user_id, _('Another Attempt Requested'), _('Attempt %s feedback: %s. Attempt %s is ready.') % (a.attempt_no, self.feedback, next_no))
        return {'type': 'ir.actions.act_window_close'}
