from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

PARAMETERS = [('inhibition','Inhibition'),('ard','ARD'),('desperation','Desperation'),('soil_stain','Soil Stain Removal'),('adw','ADW'),('other','Any Other')]
REQUESTER = 'rnd_workflow.group_rnd_sm'
REQUEST_REVIEW = 'rsd_quality.group_application_request_reviewer'
EXPERIMENT_USER = 'rsd_quality.group_application_experiment_user'
EXPERIMENT_REVIEW = 'rsd_quality.group_application_experiment_reviewer'
MANAGER = 'rnd_workflow.group_rnd_owner'
SYSTEM = 'base.group_system'

def _manager(user):
    return user.has_group(MANAGER) or user.has_group(SYSTEM)

class RSDApplicationRequest(models.Model):
    _name = 'rsd.quality.application.request'
    _description = 'R&D Application Test Request'
    _inherit = ['mail.thread','mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False, tracking=True)
    requester_id = fields.Many2one('res.users', default=lambda s:s.env.user, readonly=True, required=True, tracking=True)
    requester_employee_id = fields.Many2one('hr.employee', related='requester_id.employee_id', store=True)
    department_id = fields.Many2one('hr.department', related='requester_employee_id.department_id', store=True)
    designation = fields.Char(related='requester_employee_id.job_title', store=True)
    request_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    sample_name = fields.Char(required=True, tracking=True)
    batch_no = fields.Char(string='Batch No.')
    quantity = fields.Float(required=True)
    quantity_uom = fields.Many2one('uom.uom', string='Unit', default=lambda s:s.env.ref('uom.product_uom_kgm', raise_if_not_found=False))
    manufacturer_name = fields.Char()
    purpose = fields.Text(required=True)
    compare_performance = fields.Text(string='Compare Performance With')
    description = fields.Text(string='Description')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    delivery_mode = fields.Selection([('courier','Courier'),('hand','Hand Delivery'),('transport','Transport'),('other','Other')], required=True)
    parameter_ids = fields.Many2many('rsd.quality.application.parameter', relation='rsd_app_request_parameter_rel', column1='request_id', column2='parameter_id', string='Performance Test Parameters', required=True)
    other_parameter = fields.Char(string='Other Parameter')
    has_other_parameter = fields.Boolean(compute='_compute_has_other_parameter')
    inhibition_test_ids = fields.Many2many('rsd.quality.inhibition.test', relation='rsd_app_request_inhibition_rel', column1='request_id', column2='inhibition_test_id', string='Inhibition Tests')
    inhibition_snapshot = fields.Text(readonly=True)
    request_reviewer_id = fields.Many2one('res.users', string='Request Reviewer')
    assigned_user_id = fields.Many2one('res.users', string='Application User', tracking=True)
    experiment_reviewer_id = fields.Many2one('res.users', string='Experiment Reviewer', tracking=True)
    proposed_completion_date = fields.Date()
    request_review_feedback = fields.Text(readonly=True, tracking=True)
    state = fields.Selection([('draft','Draft'),('submitted','Submitted'),('request_revision','Request Revision'),('approved','Approved'),('experiment','Experiment In Progress'),('experiment_review','Experiment Review'),('results_sent','Results Sent to SnM'),('completed','Completed'),('cancelled','Cancelled')], default='draft', required=True, tracking=True)
    experiment_id = fields.Many2one('rsd.quality.application.experiment', compute='_compute_experiment', store=True)
    experiment_count = fields.Integer(compute='_compute_experiment')
    legacy_attempt_ids = fields.One2many('rsd.quality.application.attempt','request_id', string='Legacy Attempts')
    legacy_current_attempt_id = fields.Many2one('rsd.quality.application.attempt', compute='_compute_legacy_attempt')
    legacy_attempt_count = fields.Integer(compute='_compute_legacy_attempt')
    company_id = fields.Many2one('res.company', default=lambda s:s.env.company, required=True)
    submitted_on = fields.Datetime(readonly=True)
    approved_on = fields.Datetime(readonly=True)
    final_sent_on = fields.Datetime(readonly=True)
    closed_on = fields.Datetime(readonly=True)

    @api.depends('parameter_ids.code')
    def _compute_has_other_parameter(self):
        for r in self: r.has_other_parameter = 'other' in r.parameter_ids.mapped('code')
    @api.depends('experiment_id')
    def _compute_experiment(self):
        for r in self:
            e = self.env['rsd.quality.application.experiment'].search([('request_id','=',r.id)], limit=1)
            r.experiment_id, r.experiment_count = e, bool(e)
    @api.depends('legacy_attempt_ids.attempt_no')
    def _compute_legacy_attempt(self):
        for r in self:
            ats=r.legacy_attempt_ids.sorted('attempt_no'); r.legacy_attempt_count=len(ats); r.legacy_current_attempt_id=ats[-1] if ats else False
    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            v['requester_id']=self.env.uid; v['state']='draft'
            if v.get('name','New')=='New': v['name']=self.env['ir.sequence'].next_by_code('rsd.quality.application.request') or 'New'
        return super().create(vals_list)
    def write(self, vals):
        workflow={'state','requester_id','name','submitted_on','approved_on','final_sent_on','closed_on','request_review_feedback','request_reviewer_id','assigned_user_id','experiment_reviewer_id','inhibition_snapshot'}
        if workflow.intersection(vals): raise UserError(_('Workflow fields are controlled by workflow actions.'))
        for r in self:
            if r.state not in ('draft','request_revision') and vals: raise UserError(_('Request details are locked after submission.'))
            if r.requester_id != self.env.user and not _manager(self.env.user): raise UserError(_('Only the request owner can edit this request.'))
        return super().write(vals)
    def _wf(self, vals): return super(RSDApplicationRequest,self.sudo()).write(vals)
    def _check_requester(self):
        if any(r.requester_id != self.env.user for r in self) and not _manager(self.env.user): raise UserError(_('Only the request owner or manager can perform this action.'))
    def _check_group(self, group):
        if not self.env.user.has_group(group) and not _manager(self.env.user): raise UserError(_('You are not authorized for this workflow action.'))
    def _notify(self, user, subject, body):
        if user:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=subject, note=body)
            self.message_post(body=body, partner_ids=user.partner_id.ids)
    def action_submit_request(self):
        self._check_requester()
        for r in self:
            if r.state not in ('draft','request_revision'): raise UserError(_('Only Draft or returned requests can be submitted.'))
            if not r.parameter_ids: raise ValidationError(_('Select at least one test parameter.'))
            if 'other' in r.parameter_ids.mapped('code') and not r.other_parameter: raise ValidationError(_('Specify the Other parameter.'))
            snap='\n'.join('%s: %s'%(t.name,t.conditions) for t in r.inhibition_test_ids) or False
            r._wf({'state':'submitted','submitted_on':fields.Datetime.now(),'inhibition_snapshot':snap,'request_review_feedback':False})
            r.message_post(body=_('Sample Request submitted for Request Review.'))
            reviewers=self.env['res.users'].search([('groups_id','in',[self.env.ref(REQUEST_REVIEW).id])])
            for u in reviewers: r._notify(u,_('Sample Request Review'),_('%s is awaiting request review.')%r.name)
        return True
    def action_request_review(self):
        self.ensure_one(); self._check_group(REQUEST_REVIEW)
        if self.state!='submitted': raise UserError(_('Only submitted requests can be reviewed.'))
        return {'type':'ir.actions.act_window','res_model':'rsd.quality.application.request.review.wizard','view_mode':'form','target':'new','context':{'default_request_id':self.id}}
    def action_start_experiment(self):
        self.ensure_one(); self._check_group(EXPERIMENT_USER)
        e=self.experiment_id
        if self.state!='approved' or not e or e.assigned_user_id!=self.env.user: raise UserError(_('Only the assigned Application User can start this approved Experiment.'))
        e.action_start(); return True
    def action_resume_experiment(self):
        self.ensure_one(); self._check_group(EXPERIMENT_USER); e=self.experiment_id
        if not e or e.assigned_user_id != self.env.user or self.state != 'experiment' or e.state != 'returned': raise UserError(_('Only the assigned Application User can resume a returned Experiment.'))
        e.action_resume(); return True
    def action_submit_experiment(self):
        self.ensure_one(); e=self.experiment_id
        if not e: raise UserError(_('Experiment not found.'))
        e.action_submit(); return True
    def action_experiment_review(self):
        self.ensure_one(); self._check_group(EXPERIMENT_REVIEW)
        if self.state!='experiment_review': raise UserError(_('No Experiment is awaiting review.'))
        return {'type':'ir.actions.act_window','res_model':'rsd.quality.application.experiment.review.wizard','view_mode':'form','target':'new','context':{'default_request_id':self.id}}
    def action_sn_m_close(self):
        self.ensure_one(); self._check_requester()
        if self.state!='results_sent': raise UserError(_('Only requests with final results sent to SnM can be closed.'))
        self._wf({'state':'completed','closed_on':fields.Datetime.now()}); self.message_post(body=_('Request closed by SnM.')); return True
    def action_cancel_request(self):
        self.ensure_one(); self._check_requester()
        if self.state not in ('draft','submitted','request_revision'): raise UserError(_('This request cannot be cancelled now.'))
        self._wf({'state':'cancelled'}); return True

class RSDApplicationExperiment(models.Model):
    _name='rsd.quality.application.experiment'; _description='R&D Application Experiment'; _inherit=['mail.thread','mail.activity.mixin']
    _order='create_date desc'
    name=fields.Char(compute='_compute_name',store=True)
    request_id=fields.Many2one('rsd.quality.application.request',required=True,ondelete='cascade',index=True)
    assigned_user_id=fields.Many2one('res.users',required=True,tracking=True)
    reviewer_id=fields.Many2one('res.users',required=True,tracking=True)
    state=fields.Selection([('assigned','Assigned'),('in_progress','In Progress'),('submitted','Submitted for Review'),('returned','Returned for Rework'),('approved','Approved')],default='assigned',tracking=True)
    start_date=fields.Datetime(readonly=True,tracking=True); submitted_on=fields.Datetime(readonly=True,tracking=True); reviewed_on=fields.Datetime(readonly=True,tracking=True)
    description=fields.Text(string='Test Report / Results',tracking=True)
    attachment_ids=fields.Many2many('ir.attachment',string='Report Attachments')
    reviewer_feedback=fields.Text(readonly=True,tracking=True)
    sendback_count=fields.Integer(default=0,readonly=True)
    work_intervals=fields.One2many('rsd.quality.application.experiment.interval','experiment_id')
    work_duration_hours=fields.Float(compute='_compute_duration')
    company_id=fields.Many2one('res.company',related='request_id.company_id',store=True)
    _sql_constraints=[('request_experiment_unique','unique(request_id)','Only one Experiment is permitted per Sample Request.')]
    @api.depends('request_id.name')
    def _compute_name(self):
        for e in self: e.name=(e.request_id.name or '')+' - Experiment'
    @api.depends('work_intervals.start_date','work_intervals.end_date')
    def _compute_duration(self):
        for e in self: e.work_duration_hours=sum((i.end_date-i.start_date).total_seconds()/3600 for i in e.work_intervals if i.start_date and i.end_date)
    def write(self,vals):
        protected={'state','start_date','submitted_on','reviewed_on','reviewer_feedback','sendback_count'}
        if protected.intersection(vals): raise UserError(_('Experiment workflow fields are controlled by actions.'))
        for e in self:
            if e.state not in ('in_progress','returned') or e.assigned_user_id!=self.env.user: raise UserError(_('Only the assigned Application User may edit an active Experiment.'))
        return super().write(vals)
    def _wf(self,vals): return super(RSDApplicationExperiment,self.sudo()).write(vals)
    def action_start(self):
        self.ensure_one(); req=self.request_id
        if self.assigned_user_id!=self.env.user or req.state!='approved' or self.state!='assigned': raise UserError(_('Experiment cannot be started by this user or at this stage.'))
        now=fields.Datetime.now(); self._wf({'state':'in_progress','start_date':now}); self.env['rsd.quality.application.experiment.interval'].sudo().create({'experiment_id':self.id,'start_date':now})
        req._wf({'state':'experiment'}); req._notify(req.requester_id,_('Experiment Started'),_('%s has started the Experiment.')%self.name); self.message_post(body=_('Experiment started.')); return True
    def action_resume(self):
        self.ensure_one(); now=fields.Datetime.now()
        if self.assigned_user_id != self.env.user or self.state != 'returned': raise UserError(_('Only the assigned Application User can resume this Experiment.'))
        self._wf({'state':'in_progress','reviewer_feedback':False})
        self.env['rsd.quality.application.experiment.interval'].sudo().create({'experiment_id':self.id,'start_date':now})
        self.request_id._notify(self.request_id.requester_id,_('Experiment Resumed'),_('%s has resumed work on the Experiment.')%self.name)
        return True
    def action_submit(self):
        self.ensure_one(); req=self.request_id
        if self.assigned_user_id!=self.env.user or req.state!='experiment' or self.state not in ('in_progress','returned'): raise UserError(_('Only the assigned Application User can submit an active Experiment.'))
        if not self.description: raise ValidationError(_('Enter Test Report / Results before submitting.'))
        now=fields.Datetime.now(); open_interval=self.work_intervals.filtered(lambda i:not i.end_date)[:1]
        if open_interval: open_interval.sudo().write({'end_date':now})
        self._wf({'state':'submitted','submitted_on':now}); req._wf({'state':'experiment_review'}); req._notify(self.reviewer_id,_('Experiment Review'),_('%s is submitted and awaiting your review.')%self.name); self.message_post(body=_('Experiment submitted for review.')); return True

class RSDApplicationExperimentInterval(models.Model):
    _name='rsd.quality.application.experiment.interval'; _description='Experiment Work Interval'
    experiment_id=fields.Many2one('rsd.quality.application.experiment',required=True,ondelete='cascade')
    start_date=fields.Datetime(required=True); end_date=fields.Datetime()

class RSDApplicationParameter(models.Model):
    _name='rsd.quality.application.parameter'; _description='Application Test Parameter'; _order='sequence,name'
    name=fields.Char(required=True); code=fields.Selection(PARAMETERS,required=True); sequence=fields.Integer(default=10); active=fields.Boolean(default=True)
class RSDInhibitionTest(models.Model):
    _name='rsd.quality.inhibition.test'; _description='Inhibition Test Condition'; _order='sequence,name'
    name=fields.Char(required=True); sequence=fields.Integer(default=10); conditions=fields.Text(required=True); active=fields.Boolean(default=True)

# Keep the old Attempt model intact for upgrade compatibility and historical records.
class RSDApplicationAttempt(models.Model):
    _name='rsd.quality.application.attempt'; _description='Legacy Application Test Attempt'; _inherit=['mail.thread','mail.activity.mixin']; _order='attempt_no'
    request_id=fields.Many2one('rsd.quality.application.request',required=True,ondelete='cascade',index=True)
    attempt_no=fields.Integer(required=True,readonly=True); name=fields.Char(compute='_compute_name',store=True)
    assigned_user_id=fields.Many2one('res.users',related='request_id.assigned_user_id',store=True)
    state=fields.Selection([('in_progress','In Progress'),('submitted','Submitted for Review'),('revision_requested','Revision Requested'),('accepted','Accepted')],default='in_progress')
    start_date=fields.Date(); description=fields.Text(string='Legacy Test Report / Results'); attachment_ids=fields.Many2many('ir.attachment',string='Legacy Report Attachments')
    submitted_by=fields.Many2one('res.users'); submitted_on=fields.Datetime(); requester_feedback=fields.Text(); reviewed_by=fields.Many2one('res.users'); reviewed_on=fields.Datetime()
    @api.depends('request_id.name','attempt_no')
    def _compute_name(self):
        for a in self: a.name='%s - Legacy Attempt %s'%(a.request_id.name,a.attempt_no)

class RequestReviewWizard(models.TransientModel):
    _name='rsd.quality.application.request.review.wizard'; _description='Application Request Review Wizard'
    request_id=fields.Many2one('rsd.quality.application.request',required=True)
    decision=fields.Selection([('approve','Approve'),('return','Send Back')],required=True)
    feedback=fields.Text(); assigned_user_id=fields.Many2one('res.users',string='Application User'); reviewer_id=fields.Many2one('res.users',string='Experiment Reviewer')
    def action_confirm(self):
        self.ensure_one(); r=self.request_id; r._check_group(REQUEST_REVIEW)
        if r.state!='submitted': raise UserError(_('This request is not awaiting Request Review.'))
        if self.decision=='return' and not self.feedback: raise ValidationError(_('Feedback is required to send the request back.'))
        if self.decision=='approve':
            if not self.assigned_user_id or not self.reviewer_id: raise ValidationError(_('Assign both Application User and Experiment Reviewer.'))
            e=self.env['rsd.quality.application.experiment'].sudo().search([('request_id','=',r.id)],limit=1)
            if not e: e=self.env['rsd.quality.application.experiment'].sudo().create({'request_id':r.id,'assigned_user_id':self.assigned_user_id.id,'reviewer_id':self.reviewer_id.id})
            else: e.sudo().write({'assigned_user_id':self.assigned_user_id.id,'reviewer_id':self.reviewer_id.id})
            r._wf({'state':'approved','approved_on':fields.Datetime.now(),'request_reviewer_id':self.env.user.id,'assigned_user_id':self.assigned_user_id.id,'experiment_reviewer_id':self.reviewer_id.id,'request_review_feedback':False})
            r._notify(self.assigned_user_id,_('Experiment Assigned'),_('%s has been approved and assigned to you.')%r.name); r._notify(self.reviewer_id,_('Experiment Reviewer Assigned'),_('You are assigned to review the Experiment for %s.')%r.name)
        else:
            r._wf({'state':'request_revision','request_review_feedback':self.feedback,'request_reviewer_id':self.env.user.id}); r._notify(r.requester_id,_('Sample Request Returned'),self.feedback)
        return {'type':'ir.actions.act_window_close'}

class ExperimentReviewWizard(models.TransientModel):
    _name='rsd.quality.application.experiment.review.wizard'; _description='Experiment Review Wizard'
    request_id=fields.Many2one('rsd.quality.application.request',required=True)
    decision=fields.Selection([('approve','Approve and Send Results'),('return','Send Back to Application User')],required=True); feedback=fields.Text()
    def action_confirm(self):
        self.ensure_one(); r=self.request_id; e=r.experiment_id; r._check_group(EXPERIMENT_REVIEW)
        if r.state!='experiment_review' or not e or e.state!='submitted' or e.reviewer_id!=self.env.user: raise UserError(_('This Experiment is not awaiting your review.'))
        if self.decision=='return' and not self.feedback: raise ValidationError(_('Feedback is mandatory when sending back.'))
        now=fields.Datetime.now()
        if self.decision=='approve':
            e._wf({'state':'approved','reviewed_on':now,'reviewer_feedback':self.feedback or False}); r._wf({'state':'results_sent','final_sent_on':now}); r._notify(r.requester_id,_('Final Experiment Results'),_('Final Experiment results for %s are ready for your review.')%r.name); r._notify(e.assigned_user_id,_('Experiment Approved'),_('%s has been approved.')%e.name)
        else:
            e._wf({'state':'returned','reviewer_feedback':self.feedback,'sendback_count':e.sendback_count+1,'reviewed_on':now}); r._wf({'state':'experiment'}); interval=self.env['rsd.quality.application.experiment.interval'].sudo().search([('experiment_id','=',e.id),('end_date','=',False)],limit=1);
            if interval: interval.sudo().write({'end_date':now})
            r._notify(e.assigned_user_id,_('Experiment Returned for Rework'),self.feedback); e.message_post(body=self.feedback)
        return {'type':'ir.actions.act_window_close'}
