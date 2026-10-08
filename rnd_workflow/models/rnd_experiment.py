from odoo import api, fields, models
from odoo.exceptions import UserError


GROUP_OFFICER = 'rnd_workflow.group_rnd_officer'
GROUP_OWNER = 'rnd_workflow.group_rnd_owner'
GROUP_QC = 'rnd_workflow.group_qc_officer'
GROUP_PERFORMANCE = 'rnd_workflow.group_performance_officer'


class RndExperiment(models.Model):
    _name = 'rnd.experiment'
    _description = 'R&D Batch / Experiment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Experiment No.', readonly=True, copy=False, default='New',
        help='Mandatory experiment number, auto-generated.')
    project_id = fields.Many2one(
        'rnd.project', string='R&D Project', required=True,
        ondelete='cascade', tracking=True)
    rnd_owner_id = fields.Many2one(
        related='project_id.rnd_owner_id', string='R&D Project Owner', store=True)

    assigned_user_id = fields.Many2one('res.users', string='Assigned R&D User', tracking=True)
    execution_notes = fields.Text(string='Execution Notes')

    qc_user_id = fields.Many2one('res.users', string='QC User', tracking=True)
    qc_report = fields.Text(string='QC Report')
    qc_date = fields.Date(string='QC Report Date')

    performance_user_id = fields.Many2one('res.users', string='Performance User', tracking=True)
    performance_report = fields.Text(string='Performance Report')
    performance_date = fields.Date(string='Performance Report Date')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('assigned', 'Assigned to R&D User'),
        ('execution', 'Experiment Execution'),
        ('qc_submitted', 'Submitted for QC'),
        ('qc_accepted', 'QC Accepted'),
        ('qc_analysis', 'QC Analysis'),
        ('qc_report', 'QC Report Submitted'),
        ('performance_assigned', 'Performance Task Assigned'),
        ('performance_check', 'Performance User Checking'),
        ('performance_report', 'Performance Report Submitted'),
        ('done', 'Done'),
    ], default='draft', required=True, tracking=True, copy=False)

    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color')

    @api.model_create_multi
    def create(self, vals_list):
        if not (
            self.env.user.has_group(GROUP_OFFICER)
            or self.env.user.has_group(GROUP_OWNER)
        ):
            raise UserError('Only R&D Officers or the R&D Project Owner / Manager can create experiments.')

        for vals in vals_list:
            project = self.env['rnd.project'].browse(vals.get('project_id')).exists()
            if not project:
                raise UserError('Please select a valid R&D Project.')
            if project.state != 'execution':
                raise UserError('Experiments can be created only after the project enters Batch / Experiment Execution.')
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rnd.experiment') or 'New'
        return super().create(vals_list)

    def _check_group(self, group_xmlid, message):
        if not self.env.user.has_group(group_xmlid):
            raise UserError(message)

    def _is_owner(self):
        return self.env.user.has_group(GROUP_OWNER)

    def _notify_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'rnd_workflow.notify_stage_change', 'True'
        ) == 'True'

    def _schedule_activity(self, user, summary, note):
        if self._notify_enabled() and user:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                summary=summary,
                note=note,
            )

    def write(self, vals):
        if not vals:
            return True
        if self.env.context.get('rnd_workflow_action'):
            return super().write(vals)

        user = self.env.user
        is_owner = self._is_owner()
        is_assigned = any(rec.assigned_user_id == user for rec in self)
        is_qc = any(rec.qc_user_id == user for rec in self)
        is_performance = any(rec.performance_user_id == user for rec in self)

        if 'state' in vals:
            raise UserError('Experiment status can only be changed through the approved workflow actions.')

        if any(field in vals for field in ('name', 'project_id', 'rnd_owner_id', 'assigned_user_id',
                                           'qc_user_id', 'performance_user_id', 'qc_date', 'performance_date')):
            if not is_owner:
                raise UserError('Assignment, project, workflow and system fields can only be changed by the R&D Project Owner / Manager.')

        if 'execution_notes' in vals and not is_owner:
            for rec in self:
                if rec.assigned_user_id != user or rec.state not in ('assigned', 'execution'):
                    raise UserError('Only the assigned R&D user can update execution notes during the assigned/execution stage.')

        if 'qc_report' in vals and not is_owner:
            for rec in self:
                if rec.qc_user_id != user or rec.state != 'qc_analysis':
                    raise UserError('Only the assigned QC user can update the QC report during QC Analysis.')

        if 'performance_report' in vals and not is_owner:
            for rec in self:
                if rec.performance_user_id != user or rec.state != 'performance_check':
                    raise UserError('Only the assigned Performance user can update the performance report during Performance Check.')

        return super().write(vals)

    def unlink(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can delete experiments.')
        if any(rec.state != 'draft' for rec in self):
            raise UserError('Only Draft experiments can be deleted. Completed workflow records must be retained for audit history.')
        return super().unlink()

    # ---------------------------------------------------------------
    # Workflow actions
    # ---------------------------------------------------------------
    def action_assign(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can assign an experiment.')
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Experiment must be in Draft to assign.')
            if not rec.assigned_user_id:
                raise UserError('Please select an R&D user to assign.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'assigned'})
            rec._schedule_activity(
                rec.assigned_user_id,
                'Execute assigned experiment',
                f'Experiment {rec.name} has been assigned to you.',
            )

    def action_start_execution(self):
        for rec in self:
            if rec.state != 'assigned':
                raise UserError('Experiment must be Assigned before execution.')
            if self.env.user != rec.assigned_user_id and not self._is_owner():
                raise UserError('Only the assigned R&D user can start execution.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'execution'})

    def action_submit_qc(self):
        for rec in self:
            if rec.state != 'execution':
                raise UserError('Experiment must be in Execution to submit for QC.')
            if self.env.user != rec.assigned_user_id and not self._is_owner():
                raise UserError('Only the assigned R&D user can submit the experiment for QC.')
            if not rec.qc_user_id:
                raise UserError('Please assign a QC user before submitting for QC.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'qc_submitted'})
            rec.message_post(body='Experiment submitted for QC.')
            rec._schedule_activity(
                rec.qc_user_id,
                'Accept QC request',
                f'QC acceptance is requested for experiment {rec.name}.',
            )

    def action_qc_accept(self):
        for rec in self:
            if rec.state != 'qc_submitted':
                raise UserError('Experiment must be Submitted for QC to accept.')
            if not rec.qc_user_id:
                raise UserError('Please assign a QC user before accepting.')
            if self.env.user != rec.qc_user_id and not self._is_owner():
                raise UserError('Only the assigned QC user can accept the QC request.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'qc_accepted'})

    def action_start_qc_analysis(self):
        for rec in self:
            if rec.state != 'qc_accepted':
                raise UserError('QC request must be accepted before analysis starts.')
            if self.env.user != rec.qc_user_id and not self._is_owner():
                raise UserError('Only the assigned QC user can start QC analysis.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'qc_analysis'})

    def action_submit_qc_report(self):
        for rec in self:
            if rec.state != 'qc_analysis':
                raise UserError('Experiment must be in QC Analysis to submit report.')
            if self.env.user != rec.qc_user_id and not self._is_owner():
                raise UserError('Only the assigned QC user can submit the QC report.')
            if not rec.qc_report:
                raise UserError('Please fill in the QC report before submitting.')
            rec.with_context(rnd_workflow_action=True).write({
                'qc_date': fields.Date.context_today(rec),
                'state': 'qc_report',
            })
            rec.message_post(body='QC report submitted.')
            rec._schedule_activity(
                rec.rnd_owner_id,
                'Review QC result',
                f'QC report submitted for experiment {rec.name}.',
            )

    def action_assign_performance(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can assign the performance check.')
        for rec in self:
            if rec.state != 'qc_report':
                raise UserError('QC report must be submitted before assigning performance check.')
            if not rec.performance_user_id:
                raise UserError('Please select a performance user.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'performance_assigned'})
            rec._schedule_activity(
                rec.performance_user_id,
                'Perform performance check',
                f'Performance check requested for experiment {rec.name}.',
            )

    def action_start_performance_check(self):
        for rec in self:
            if rec.state != 'performance_assigned':
                raise UserError('Performance task must be assigned before checking.')
            if self.env.user != rec.performance_user_id and not self._is_owner():
                raise UserError('Only the assigned Performance user can start the performance check.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'performance_check'})

    def action_submit_performance_report(self):
        for rec in self:
            if rec.state != 'performance_check':
                raise UserError('Experiment must be in Performance Check to submit report.')
            if self.env.user != rec.performance_user_id and not self._is_owner():
                raise UserError('Only the assigned Performance user can submit the performance report.')
            if not rec.performance_report:
                raise UserError('Please fill in the performance report before submitting.')
            rec.with_context(rnd_workflow_action=True).write({
                'performance_date': fields.Date.context_today(rec),
                'state': 'performance_report',
            })
            rec.message_post(body='Performance report submitted.')
            rec._schedule_activity(
                rec.rnd_owner_id,
                'Final review of experiment',
                f'Performance report submitted for experiment {rec.name}.',
            )

    def action_done(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can finalize an experiment.')
        for rec in self:
            if rec.state != 'performance_report':
                raise UserError('Performance report must be submitted before closing the experiment.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'done'})
            rec.message_post(body='Experiment finalized.')

    def action_reset_to_draft(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can reset an experiment.')
        for rec in self:
            if rec.state == 'done':
                raise UserError('A completed experiment cannot be reset to draft. Create a new experiment if a rerun is required.')
            rec.with_context(rnd_workflow_action=True).write({
                'state': 'draft',
                'qc_date': False,
                'performance_date': False,
            })
