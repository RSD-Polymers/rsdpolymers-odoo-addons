from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = "mrp.production"

    tare_weight = fields.Float("Tare Weight (KG)")
    output_form_completion_in_progress = fields.Boolean(
        string="Output Form Completion In Progress", default=False, copy=False,
        help="Internal transaction flag used only while standard Produce All is executing.",
    )

    packed_by = fields.Many2one(
        "res.users",
        string="Packed By"
    )

    prepared_by = fields.Many2one(
        "res.users",
        string="Prepared By",
        default=lambda self: self.env.user,
        readonly=True
    )

    rm_issue_status = fields.Selection([
        ('not_requested', 'Not Requested'),
        ('requested', 'Waiting RM Issue'),
        ('issued', 'RM Issued')
    ], default='not_requested', tracking=True)

    show_request_rm_button = fields.Boolean(
        compute="_compute_show_request_rm_button"
    )

    rm_issue_not_required = fields.Boolean(compute="_compute_rm_issue_not_required")

    show_rm_issue_smart_button = fields.Boolean(
        compute="_compute_show_rm_issue_smart_button"
    )

    rm_issue_id = fields.Many2one('rm.issue', string="Latest RM Issue")
    rm_issue_count = fields.Integer(compute="_compute_rm_issue_count")
    rm_return_count = fields.Integer(compute="_compute_rm_return_count")

    production_request_line_id = fields.Many2one(
        'production.request.line',
        string='Production Request Line',
        readonly=False,
        index=True,
        copy=False,
        help='The single Production Request Line this Manufacturing Order or Packing Instruction executes.',
    )
    production_request_id = fields.Many2one(
        related='production_request_line_id.request_id',
        string='Production Request',
        readonly=True,
        store=True,
        index=True,
    )
    production_request_count = fields.Integer(compute="_compute_production_request_count")

    @api.constrains('production_request_line_id', 'product_id', 'product_qty', 'product_uom_id')
    def _check_production_request_link(self):
        for mo in self:
            line = mo.production_request_line_id
            if not line:
                continue
            if mo.product_id != line.product_id:
                raise UserError(_(
                    'The Manufacturing Order/Packing Instruction product must match Production Request Line %s.'
                ) % line.product_id.display_name)
            if mo.product_uom_id.category_id != line.product_uom_id.category_id:
                raise UserError(_('The Production Request Line and Manufacturing Order must use compatible Units of Measure.'))
            if mo.state == 'cancel':
                continue
            allocated = line.allocated_qty
            if allocated > line.shortage_qty + 1e-6:
                raise UserError(_(
                    'Execution quantity for %s exceeds the Production Request shortage by %s %s.'
                ) % (line.product_id.display_name, allocated - line.shortage_qty, line.product_uom_id.name))

    def write(self, vals):
        if 'output_form_completion_in_progress' in vals:
            raise UserError(_('The internal Output Form completion flag cannot be changed manually.'))

        # Lock the Manufacturing Order while its Output Form is awaiting
        # approval or has been approved. The lock is released only when the
        # Manager rejects/sends the form back (state becomes rejected/returned).
        # Standard Produce All is allowed only during the protected internal
        # completion transaction started by button_mark_done below.
        locked_forms = self.env['production.output.form'].sudo().search([
            ('production_id', 'in', self.ids),
            ('state', 'in', ('submitted', 'approved', 'produced')),
        ])
        if locked_forms and set(vals) - {'message_follower_ids', 'message_partner_ids'}:
            locked_mo_ids = set(locked_forms.mapped('production_id').ids)
            internal_completion = all(
                mo.id not in locked_mo_ids or mo.output_form_completion_in_progress
                for mo in self
            )
            if not internal_completion:
                raise UserError(_(
                    'This Manufacturing Order is locked by its submitted or approved Output Form. '
                    'Only a Manufacturing Manager can send the Output Form back to Production.'
                ))

        if 'production_request_line_id' in vals:
            for mo in self:
                if mo.production_request_line_id.id != vals.get('production_request_line_id') and mo.state != 'draft':
                    raise UserError(_('The Production Request Line cannot be changed after the document is confirmed.'))
        old_lines = self.mapped('production_request_line_id')
        res = super().write(vals)
        affected_lines = old_lines | self.mapped('production_request_line_id')
        if affected_lines:
            affected_lines.mapped('request_id')._sync_state_from_lines()
        return res

    def _compute_production_request_count(self):
        for mo in self:
            mo.production_request_count = 1 if mo.production_request_line_id else 0

    def action_view_production_requests(self):
        self.ensure_one()
        if not self.production_request_line_id:
            raise UserError(_('No Production Request Line is linked to this document.'))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Production Request',
            'res_model': 'production.request',
            'view_mode': 'form',
            'res_id': self.production_request_line_id.request_id.id,
            'target': 'current',
        }

    def _compute_rm_issue_count(self):
        for mo in self:
            mo.rm_issue_count = self.env['rm.issue'].search_count([('mo_id', '=', mo.id)])

    def _compute_rm_return_count(self):
        for mo in self:
            mo.rm_return_count = self.env['rm.return'].search_count([('mo_id', '=', mo.id)])

    def _compute_prepared_by(self):
        for rec in self:
            rec.prepared_by = rec.create_uid.name

    def _is_unpack_only_components(self):
        """True only when this MO has components and every active component is FG Un-Pack."""
        self.ensure_one()
        category = self.env['product.category'].search([
            ('complete_name', '=', 'All / Sales / Finished Goods (Un-Pack)')
        ], limit=1)
        if not category:
            return False
        unpack_category_ids = self.env['product.category'].search([
            ('id', 'child_of', category.id)
        ]).ids
        components = self.move_raw_ids.filtered(lambda move: move.state != 'cancel' and move.product_id)
        return bool(components) and all(
            move.product_id.categ_id and move.product_id.categ_id.id in unpack_category_ids
            for move in components
        )

    @api.depends('state', 'product_qty', 'qty_producing', 'rm_issue_status', 'is_packing_order', 'move_raw_ids', 'move_raw_ids.product_id', 'move_raw_ids.state')
    def _compute_show_produce(self):
        super()._compute_show_produce()
        for production in self:
            # If every component is FG Un-Pack, RM Issue is not required for this MO.
            if not production.is_packing_order and production.rm_issue_status != 'issued' and not production._is_unpack_only_components():
                production.show_produce = False
                production.show_produce_all = False

    @api.depends('is_packing_order', 'move_raw_ids', 'move_raw_ids.product_id', 'move_raw_ids.state')
    def _compute_rm_issue_not_required(self):
        for rec in self:
            rec.rm_issue_not_required = not rec.is_packing_order and rec._is_unpack_only_components()

    @api.depends('is_packing_order', 'move_raw_ids', 'move_raw_ids.product_id', 'move_raw_ids.state')
    def _compute_show_request_rm_button(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')

        is_production = False
        if user.employee_id and user.employee_id.department_id:
            is_production = user.employee_id.department_id.name.strip().lower() == "production"

        for rec in self:
            has_active_rm_issue = bool(self.env['rm.issue'].sudo().search_count([
                ('mo_id', '=', rec.id),
                ('state', '!=', 'cancelled'),
            ]))
            rec.show_request_rm_button = (
                (is_admin or is_production)
                and not rec._is_unpack_only_components()
                and not has_active_rm_issue
            )

    def _compute_show_rm_issue_smart_button(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')

        is_store = False
        if user.employee_id and user.employee_id.department_id:
            is_store = user.employee_id.department_id.name.strip().lower() == "store"

        for rec in self:
            rec.show_rm_issue_smart_button = is_admin or is_store

    # -----------------------------------------------------
    # RM ISSUE REQUEST (Production → Store)
    # -----------------------------------------------------


    def _check_output_form_eligibility(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'progress', 'to_close'):
            raise UserError(_('Only confirmed, in-progress or To Close Manufacturing Orders can have an Output Form.'))
        if not getattr(self, 'qc_batch_eligible', False):
            raise UserError(_('This Manufacturing Order has not passed all required QC gates (Unloading, Performance Test and Internal COA).'))
        if self.is_packing_order:
            raise UserError(_('Packing Orders are not eligible for the Production Output Form.'))
        return True

    def action_create_output_form(self):
        self.ensure_one()
        if not (self.env.user.has_group('mrp.group_mrp_user') or self.env.user.has_group('mrp.group_mrp_manager') or self.env.user.has_group('base.group_system')):
            raise UserError(_('Only Production users can create an Output Form.'))
        self._check_output_form_eligibility()
        existing = self.env['production.output.form'].search([('production_id', '=', self.id), ('state', '!=', 'cancelled')], limit=1)
        if existing:
            return {'type': 'ir.actions.act_window', 'res_model': 'production.output.form', 'view_mode': 'form', 'res_id': existing.id, 'target': 'current'}
        form = self.env['production.output.form'].create({'production_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': 'production.output.form', 'view_mode': 'form', 'res_id': form.id, 'target': 'current'}

    def action_open_eligible_output_mos(self):
        """Open only MOs that currently satisfy all QC gates and have no active form."""
        candidates = self.search([
            ('state', 'in', ('confirmed', 'progress', 'to_close')),
            ('is_packing_order', '=', False),
        ])
        eligible = candidates.filtered(lambda mo: mo.qc_batch_eligible)
        active_forms = self.env['production.output.form'].sudo().search([
            ('production_id', 'in', eligible.ids), ('state', '!=', 'cancelled'),
        ])
        eligible -= active_forms.mapped('production_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Eligible Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', eligible.ids)],
            'context': {'create': False},
        }

    def button_mark_done(self):
        output_forms = self.env['production.output.form'].sudo().search([
            ('production_id', 'in', self.ids), ('state', '!=', 'cancelled'),
        ])
        for mo in self:
            form = output_forms.filtered(lambda item: item.production_id == mo)[:1]
            if not mo.is_packing_order:
                if not form or form.state != 'approved':
                    raise UserError(_('An approved Output Form is required before Produce All.'))
                if not (self.env.user.has_group('rsd_quality.group_unloading_request_supervisor') or self.env.user.has_group('base.group_system')):
                    raise UserError(_('Only an authorised Production Supervisor can use Produce All after Output Form approval.'))
                mo._check_output_form_eligibility()
                pending_returns = self.env['rm.return'].search_count([
                    ('mo_id', '=', mo.id), ('state', 'in', ['draft', 'submitted']),
                ])
                if pending_returns:
                    raise UserError(_('Complete or cancel all Draft/Submitted RM Return requests before using Produce All.'))
        # Set a protected database flag (not a caller-controlled context key) so
        # standard stock move validation can run only inside this transaction.
        for mo in self.filtered(lambda item: not item.is_packing_order):
            super(MrpProduction, mo).write({'output_form_completion_in_progress': True})
        try:
            result = super(MrpProduction, self).button_mark_done()
        finally:
            for mo in self.filtered(lambda item: item.output_form_completion_in_progress):
                super(MrpProduction, mo).write({'output_form_completion_in_progress': False})
        for form in output_forms.filtered(lambda item: item.state == 'approved' and item.production_id.state == 'done'):
            form.sudo()._mark_produced_after_completion()
            form.message_post(body=_('Manufacturing Order successfully completed through standard Produce All. QA can now proceed with post-production inspection.'))
            qa_group = self.env.ref('rsd_qa_management.group_qa_officer', raise_if_not_found=False)
            if qa_group:
                for qa_user in qa_group.users:
                    form.production_id.activity_schedule(
                        'mail.mail_activity_data_todo', user_id=qa_user.id,
                        summary=_('Post-production QA inspection'),
                        note=_('Output Form %s has been produced. Please accept and complete the post-production QA inspection.') % form.name,
                    )
        return result

    def _check_rm_function_state(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'progress', 'to_close'):
            raise UserError(_('RM Issue and RM Return are available only when the MO is Confirmed, In Progress or To Close.'))
        if self.is_packing_order:
            raise UserError(_('RM Issue and RM Return are not available for Packing Orders.'))

    def action_request_rm_issue(self):
        self.ensure_one()
        self._check_rm_function_state()
        if self._is_unpack_only_components():
            raise UserError(_('RM Issue is not required because all components of this Manufacturing Order are Finished Goods (Un-Pack).'))

        # Serialize requests for this MO so concurrent clicks cannot create duplicates.
        self.env.cr.execute(
            'SELECT id FROM mrp_production WHERE id = %s FOR UPDATE', (self.id,)
        )
        active_rm_issue = self.env['rm.issue'].sudo().search([
            ('mo_id', '=', self.id),
            ('state', '!=', 'cancelled'),
        ], limit=1)
        if active_rm_issue:
            raise UserError(_(
                'An active RM Issue (%s) already exists for this Manufacturing Order. '
                'Cancel it before creating another RM Issue.'
            ) % active_rm_issue.name)

        rm_issue = self.env['rm.issue'].create({
            'mo_id': self.id,
            'sale_id': self.origin_sale_id.id if self.origin_sale_id else False,
            'company_id': self.company_id.id,
        })
        excluded_category = self.env['product.category'].search([('complete_name', '=', 'All / Sales / Finished Goods (Un-Pack)')], limit=1)
        lines = []
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel' and m.product_id):
            if excluded_category and move.product_id.categ_id and move.product_id.categ_id.id in self.env['product.category'].search([('id', 'child_of', excluded_category.id)]).ids:
                continue
            lines.append((0, 0, {'product_id': move.product_id.id, 'qty': move.product_uom_qty, 'uom_id': move.product_uom.id}))
        if lines:
            rm_issue.line_ids = lines
        self.rm_issue_id = rm_issue.id
        return {'type': 'ir.actions.act_window', 'name': _('RM Issue'), 'res_model': 'rm.issue', 'view_mode': 'form', 'res_id': rm_issue.id, 'target': 'current'}

    def action_request_rm_return(self):
        self.ensure_one()
        self._check_rm_function_state()
        return {'type': 'ir.actions.act_window', 'name': _('RM Return'), 'res_model': 'rm.return', 'view_mode': 'form', 'context': {'default_mo_id': self.id, 'default_company_id': self.company_id.id}, 'target': 'current'}

    def action_view_rm_returns(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('RM Returns'), 'res_model': 'rm.return', 'view_mode': 'list,form', 'domain': [('mo_id', '=', self.id)], 'target': 'current'}

    def action_view_rm_issue(self):
        self.ensure_one()
        issues = self.env['rm.issue'].search([('mo_id', '=', self.id)], order='id desc')
        if len(issues) == 1:
            return {'type': 'ir.actions.act_window', 'name': _('RM Issue'), 'res_model': 'rm.issue', 'view_mode': 'form', 'res_id': issues.id, 'target': 'current'}
        return {'type': 'ir.actions.act_window', 'name': _('RM Issues'), 'res_model': 'rm.issue', 'view_mode': 'list,form', 'domain': [('mo_id', '=', self.id)], 'target': 'current'}