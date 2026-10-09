from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = "mrp.production"

    tare_weight = fields.Float("Tare Weight (KG)")

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
            rec.show_request_rm_button = (is_admin or is_production) and not rec._is_unpack_only_components()

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


    def button_mark_done(self):
        for mo in self:
            if not mo.is_packing_order:
                pending_returns = self.env['rm.return'].search_count([
                    ('mo_id', '=', mo.id),
                    ('state', 'in', ['draft', 'submitted']),
                ])
                if pending_returns:
                    raise UserError(_(
                        'Complete or cancel all Draft/Submitted RM Return requests before using Produce All.'
                    ))
        return super().button_mark_done()

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
        # Keep one editable draft per MO, but allow repeated requests after submission.
        draft = self.env['rm.issue'].search([('mo_id', '=', self.id), ('state', '=', 'draft')], limit=1)
        if draft:
            return {'type': 'ir.actions.act_window', 'name': _('RM Issue'), 'res_model': 'rm.issue', 'view_mode': 'form', 'res_id': draft.id, 'target': 'current'}

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