from odoo import api, fields, models
from odoo.exceptions import UserError


GROUP_SM = 'rnd_workflow.group_rnd_sm'
GROUP_OWNER = 'rnd_workflow.group_rnd_owner'


class RndProject(models.Model):
    _name = 'rnd.project'
    _description = 'R&D Project Requirement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Requirement Title', required=True, tracking=True)
    code = fields.Char(string='Reference', readonly=True, copy=False, default='New')

    sm_user_id = fields.Many2one(
        'res.users', string='Requested By (Sales & Marketing)',
        default=lambda self: self.env.user, tracking=True)
    rnd_owner_id = fields.Many2one(
        'res.users', string='R&D Project Owner', tracking=True,
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'rnd_workflow.default_owner_id') and self.env['res.users'].browse(
                int(self.env['ir.config_parameter'].sudo().get_param(
                    'rnd_workflow.default_owner_id'))) or False)

    description = fields.Text(string='Requirement Description')
    delivery_date = fields.Date(string='Delivery Date to S&M', tracking=True)

    planning_type_ids = fields.Many2many(
        'rnd.planning.type', string='Planning Type(s)',
        help='Proposal / BMP / RM & Equipment Planning')

    experiment_ids = fields.One2many('rnd.experiment', 'project_id', string='Batches / Experiments')
    experiment_count = fields.Integer(compute='_compute_experiment_count')

    final_review_notes = fields.Text(string='Final Review Notes')

    state = fields.Selection([
        ('draft', 'New Requirement'),
        ('rnd_review', 'R&D Review'),
        ('planning', 'Project Planning'),
        ('execution', 'Batch / Experiment Execution'),
        ('final_review', 'Final Review'),
        ('closed', 'Closed'),
    ], default='draft', tracking=True, required=True, copy=False)

    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color')

    @api.depends('experiment_ids')
    def _compute_experiment_count(self):
        for rec in self:
            rec.experiment_count = len(rec.experiment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        if not (
            self.env.user.has_group(GROUP_SM)
            or self.env.user.has_group(GROUP_OWNER)
        ):
            raise UserError('Only Sales & Marketing or the R&D Project Owner / Manager can create requirements.')

        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('rnd.project') or 'New'
            if not vals.get('sm_user_id'):
                vals['sm_user_id'] = self.env.user.id
        return super().create(vals_list)

    def _check_group(self, group_xmlid, message):
        if not self.env.user.has_group(group_xmlid):
            raise UserError(message)

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
        is_owner = user.has_group(GROUP_OWNER)
        is_sm = user.has_group(GROUP_SM)

        if 'state' in vals and not self.env.context.get('rnd_workflow_action'):
            raise UserError('Project status can only be changed through the approved workflow actions.')
        if any(field in vals for field in ('code', 'experiment_ids')) and not is_owner:
            raise UserError('System/workflow relation fields can only be changed by the R&D Project Owner / Manager.')

        if 'rnd_owner_id' in vals and not is_owner:
            raise UserError('Only the R&D Project Owner / Manager can assign the R&D Project Owner.')

        if 'planning_type_ids' in vals and not is_owner:
            raise UserError('Only the R&D Project Owner / Manager can update planning types.')

        if 'delivery_date' in vals and not is_owner:
            raise UserError('Only the R&D Project Owner / Manager can set the delivery date.')

        if 'final_review_notes' in vals and not is_owner:
            raise UserError('Only the R&D Project Owner / Manager can update final review notes.')

        if not is_owner and is_sm:
            for rec in self:
                if rec.state != 'draft' and any(
                    field in vals for field in ('name', 'description', 'sm_user_id')
                ):
                    raise UserError('Sales & Marketing can edit the requirement only while it is New.')
        elif not is_owner and not is_sm and any(
            field in vals for field in ('name', 'description', 'sm_user_id')
        ):
            raise UserError('You are not allowed to edit Sales & Marketing requirement details.')

        return super().write(vals)

    # ---------------------------------------------------------------
    # Workflow actions
    # ---------------------------------------------------------------
    def action_submit_to_rnd(self):
        """Sales & Marketing submits the requirement to R&D."""
        self._check_group(GROUP_SM, 'Only Sales & Marketing users can submit a new requirement to R&D.')
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only a new requirement can be submitted.')
            if rec.sm_user_id != self.env.user:
                raise UserError('Only the Sales & Marketing requester can submit this requirement.')
            if not rec.rnd_owner_id:
                raise UserError('Please assign an R&D Project Owner before submitting the requirement.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'rnd_review'})
            rec.message_post(body='Requirement submitted to R&D.')
            rec._schedule_activity(
                rec.rnd_owner_id,
                'Review & accept R&D requirement',
                f'Please review requirement "{rec.name}" and provide a delivery date.',
            )

    def action_accept(self):
        """R&D project owner reviews & accepts, delivery date must be set."""
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can accept a requirement.')
        for rec in self:
            if rec.state != 'rnd_review':
                raise UserError('Requirement must be in R&D Review to accept.')
            if not rec.rnd_owner_id:
                raise UserError('Please assign an R&D Project Owner first.')
            if not rec.delivery_date:
                raise UserError('Please provide a delivery date before accepting.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'planning'})
            rec.message_post(body=f'Requirement accepted. Delivery date: {rec.delivery_date}.')
            rec._schedule_activity(
                rec.sm_user_id,
                'Delivery date confirmed',
                f'R&D has accepted the requirement. Delivery date: {rec.delivery_date}.',
            )

    def action_start_execution(self):
        """Move from planning into batch/experiment execution."""
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can start project execution.')
        for rec in self:
            if rec.state != 'planning':
                raise UserError('Project must be in Planning to start execution.')
            if not rec.planning_type_ids:
                raise UserError('Please select at least one planning type (Proposal / BMP / RM & Equipment).')
            rec.with_context(rnd_workflow_action=True).write({'state': 'execution'})
            rec.message_post(body='Project planning complete. Moved to batch/experiment execution.')

    def action_final_review(self):
        """R&D project owner performs the final review once all experiments are done."""
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can move a project to final review.')
        for rec in self:
            if rec.state != 'execution':
                raise UserError('Project must be in Execution to move to final review.')
            if not rec.experiment_ids:
                raise UserError('Create at least one experiment/batch before final review.')
            unfinished = rec.experiment_ids.filtered(lambda e: e.state != 'done')
            if unfinished:
                raise UserError('All experiments/batches must be Done before final review.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'final_review'})
            rec.message_post(body='All experiments completed. Project moved to final review.')

    def action_close(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can close a project.')
        for rec in self:
            if rec.state != 'final_review':
                raise UserError('Project must be in Final Review to close.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'closed'})
            rec.message_post(body='Project finalized and closed.')

    def action_reset_to_draft(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can reset a project.')
        for rec in self:
            if rec.state == 'closed':
                raise UserError('A closed project cannot be reset to draft.')
            rec.with_context(rnd_workflow_action=True).write({'state': 'draft'})

    def unlink(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can delete requirements.')
        if any(rec.state != 'draft' for rec in self):
            raise UserError('Only New Requirement records can be deleted. Submitted records must be retained for audit history.')
        return super().unlink()

    def action_view_experiments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Batches / Experiments',
            'res_model': 'rnd.experiment',
            'view_mode': 'list,kanban,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }
