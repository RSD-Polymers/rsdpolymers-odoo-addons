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

    show_rm_issue_smart_button = fields.Boolean(
        compute="_compute_show_rm_issue_smart_button"
    )

    rm_issue_id = fields.Many2one('rm.issue', string="RM Issue")
    rm_issue_count = fields.Integer(compute="_compute_rm_issue_count")

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
            mo.rm_issue_count = self.env['rm.issue'].search_count([
                ('mo_id', '=', mo.id)
            ])

    def _compute_prepared_by(self):
        for rec in self:
            rec.prepared_by = rec.create_uid.name

    @api.depends('state', 'product_qty', 'qty_producing', 'rm_issue_status', 'is_packing_order')
    def _compute_show_produce(self):

        super()._compute_show_produce()

        for production in self:

            # Block production until RM is issued
            if not production.is_packing_order and production.rm_issue_status != 'issued':
                production.show_produce = False
                production.show_produce_all = False

    def _compute_show_request_rm_button(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')

        is_production = False
        if user.employee_id and user.employee_id.department_id:
            is_production = user.employee_id.department_id.name.strip().lower() == "production"

        for rec in self:
            rec.show_request_rm_button = is_admin or is_production

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

    def action_request_rm_issue(self):

        for mo in self:

            if mo.is_packing_order:
                continue

            if mo.state not in ('confirmed', 'progress'):
                raise UserError("RM Issue Request can only be sent after confirming the MO.")

            # ✅ Create RM Issue document
            rm_issue = self.env['rm.issue'].create({
                'mo_id': mo.id,
                'sale_id': mo.origin_sale_id.id if mo.origin_sale_id else False,
                'company_id': mo.company_id.id,
            })

            # ✅ Create lines from BOM
            lines = []
            for line in mo.move_raw_ids:
                lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'qty': line.product_uom_qty,
                    'uom_id': line.product_uom.id,
                }))

            rm_issue.line_ids = lines

            rm_issue.action_mark_requested()

            mo.rm_issue_id = rm_issue.id
            mo.rm_issue_status = 'requested'

            body = f"""
                <p>Hello Store Team,</p>

                <p>Raw material issue has been requested for the following Manufacturing Order:</p>

                <p>
                    <b>MO:</b> {mo.name}<br/>
                    <b>Product:</b> {mo.product_id.display_name}<br/>
                    <b>Quantity:</b> {mo.product_qty}
                </p>

                <p>Please issue the required raw materials.</p>
            """

            mail_values = {
                'subject': f'RM Issue Request for {mo.name}',
                'body_html': body,
                'email_to': 'store@rsdpolymers.com',
                'email_from': 'production@rsdpolymers.com',
            }

            self.env['mail.mail'].sudo().create(mail_values).send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'RM Issue Request sent to Store Department.',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }

    def action_view_rm_issue(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'RM Issue',
            'res_model': 'rm.issue',
            'view_mode': 'form',
            'res_id': self.rm_issue_id.id,
        }