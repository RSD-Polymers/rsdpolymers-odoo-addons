from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


GROUP_OWNER = 'rnd_workflow.group_rnd_owner'


class RndProject(models.Model):
    _name = 'rnd.project'
    _description = 'R&D Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Project Name', required=True, tracking=True)
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

    description = fields.Text(string='Project Scope / Description')
    delivery_date = fields.Date(string='Committed Completion Date', tracking=True)
    deadline = fields.Date(string='Project Deadline', tracking=True, index=True)
    requirement_id = fields.Many2one('rnd.requirement', string='Source Requirement',
                                     readonly=True, copy=False, index=True)

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

    _sql_constraints = [
        ('requirement_unique', 'unique(requirement_id)',
         'An R&D requirement can be converted into only one project.'),
    ]

    @api.constrains('rnd_owner_id')
    def _check_rnd_owner_group(self):
        owner_group = self.env.ref(GROUP_OWNER)
        for rec in self:
            if rec.rnd_owner_id and owner_group not in rec.rnd_owner_id.groups_id:
                raise ValidationError('The R&D Project Owner must belong to the R&D Manager group.')

    @api.depends('experiment_ids')
    def _compute_experiment_count(self):
        for rec in self:
            rec.experiment_count = len(rec.experiment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group(GROUP_OWNER):
            raise UserError('Only the R&D Manager can create R&D projects.')
        for vals in vals_list:
            if not vals.get('requirement_id'):
                raise UserError('Create R&D projects from an accepted R&D Requirement.')
            requirement = self.env['rnd.requirement'].browse(vals['requirement_id']).exists()
            if not requirement or requirement.state != 'accepted':
                raise UserError('Projects can only be created from accepted R&D requirements.')
            if requirement.project_id:
                raise UserError('This requirement has already been converted into a project.')
            if not requirement.rnd_owner_id or not requirement.expected_completion_date:
                raise UserError('The accepted requirement must have an R&D owner and committed completion date.')
            vals['name'] = requirement.name
            vals['sm_user_id'] = requirement.requester_id.id
            vals['rnd_owner_id'] = requirement.rnd_owner_id.id
            vals['delivery_date'] = requirement.expected_completion_date
            vals['deadline'] = requirement.expected_completion_date
            vals['state'] = 'planning'
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('rnd.project') or 'New'
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

    def _workflow_write(self, vals):
        """Internal write for workflow actions after their authorization checks."""
        return super().write(vals)

    def write(self, vals):
        if not vals:
            return True
        if not self.env.user.has_group(GROUP_OWNER):
            raise UserError('Only the R&D Manager can modify R&D project records.')
        if 'state' in vals:
            raise UserError('Project status can only be changed through the approved workflow actions.')
        if 'requirement_id' in vals or 'code' in vals or 'experiment_ids' in vals:
            raise UserError('System/workflow relation fields cannot be changed manually.')
        vals = dict(vals)
        if 'deadline' in vals and 'delivery_date' in vals and vals['deadline'] != vals['delivery_date']:
            raise UserError('Project Deadline and Committed Completion Date must match.')
        if 'deadline' in vals and 'delivery_date' not in vals:
            vals['delivery_date'] = vals['deadline']
        elif 'delivery_date' in vals and 'deadline' not in vals:
            vals['deadline'] = vals['delivery_date']
        result = super().write(vals)
        for rec in self.filtered('requirement_id'):
            requirement_vals = {}
            if 'deadline' in vals:
                requirement_vals['expected_completion_date'] = rec.deadline
            if 'rnd_owner_id' in vals:
                requirement_vals['rnd_owner_id'] = rec.rnd_owner_id.id
            if requirement_vals:
                rec.requirement_id._workflow_write(requirement_vals)
        return result

    # ---------------------------------------------------------------
    # Workflow actions
    # ---------------------------------------------------------------
    def action_migrate_legacy_to_planning(self):
        """Move pre-upgrade requirement-style project records into the project workflow."""
        self._check_group(GROUP_OWNER, 'Only the R&D Manager can migrate legacy project records.')
        for rec in self:
            if rec.state not in ('draft', 'rnd_review'):
                raise UserError('Only legacy New Requirement / R&D Review records can be migrated.')
            if not rec.rnd_owner_id:
                raise UserError('Assign an R&D Project Owner before migrating this legacy record.')
            if not rec.delivery_date:
                raise UserError('Enter the committed delivery date before migrating this legacy record.')
            rec._workflow_write({
                'deadline': rec.delivery_date,
                'state': 'planning',
            })
            rec.message_post(body='Legacy requirement record migrated into the R&D project workflow.')

    def action_start_execution(self):
        """Move from planning into batch/experiment execution."""
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can start project execution.')
        for rec in self:
            if rec.state != 'planning':
                raise UserError('Project must be in Planning to start execution.')
            if not rec.planning_type_ids:
                raise UserError('Please select at least one planning type (Proposal / BMP / RM & Equipment).')
            rec._workflow_write({'state': 'execution'})
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
            rec._workflow_write({'state': 'final_review'})
            rec.message_post(body='All experiments completed. Project moved to final review.')

    def action_close(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can close a project.')
        for rec in self:
            if rec.state != 'final_review':
                raise UserError('Project must be in Final Review to close.')
            rec._workflow_write({'state': 'closed'})
            rec.message_post(body='Project finalized and closed.')

    def action_reset_to_draft(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can reset a project.')
        for rec in self:
            if rec.state == 'closed':
                raise UserError('A closed project cannot be reset to draft.')
            rec._workflow_write({'state': 'draft'})

    def unlink(self):
        self._check_group(GROUP_OWNER, 'Only the R&D Project Owner / Manager can delete requirements.')
        if any(rec.state != 'draft' for rec in self):
            raise UserError('Only legacy Draft records can be deleted. Active projects must be retained for audit history.')
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
