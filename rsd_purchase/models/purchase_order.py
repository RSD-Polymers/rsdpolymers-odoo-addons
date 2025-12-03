# -*- coding: utf-8 -*-
from odoo import fields, models, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # The custom flag for the user to select
    is_work_order = fields.Boolean(
        string="Is Work Order",
        default=False,
        help="Check this if the PO is for a service that requires a detailed Work Order printout."
    )

    ship_to_address_id = fields.Many2one(
        'res.partner',
        string='Ship To Address',
        domain=lambda self: self._get_ship_to_domain(),
        help="Select the specific address where the purchased goods should be shipped. Restricted to your company's addresses."
    )

    other_references = fields.Char(string="Other References")
    dispatch_through = fields.Char(string="Dispatched Through")
    delivery_terms = fields.Text(string="Terms of Delivery")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'RFQ Sent'),
        ('to approve', 'To Approve'),
        ('purchase', 'Purchase Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, index=True, copy=False, default='draft', tracking=True)

    @api.model
    def _get_ship_to_domain(self):
        """
        Dynamic domain for Ship To Address:
        - Includes company's main partner (id = company_id.partner_id)
        - Includes child contacts with type='delivery'
        - Works even if creating a new record (uses context company)
        """
        company = self.company_id or self.env.company
        if company and company.partner_id:
            partner_id = company.partner_id.id
            return ['|',
                    ('id', '=', partner_id),
                    '&',
                    ('parent_id', '=', partner_id),
                    ('type', '=', 'delivery')]
        return [('id', 'in', [])]  # No company -> empty domain

    @api.model_create_multi
    def create(self, vals_list):
        # Override the create method to apply custom numbering

        for vals in vals_list:
            # Check if the work order flag is set AND the name is not yet set
            if vals.get('is_work_order') and vals.get('name', 'New') == 'New':
                # Fetch the next sequence number for the Work Order
                vals['name'] = self.env['ir.sequence'].next_by_code('purchase.order.work.order') or '/'

        return super(PurchaseOrder, self).create(vals_list)

    def _approval_allowed(self):
        self.ensure_one()
        # Only Purchase Managers can auto-approve
        return self.env.user.has_group('purchase.group_purchase_manager')

    def button_approve(self, force=False):
        """Standard approval — GRN handled separately."""
        return super(PurchaseOrder, self).button_approve(force=force)

    def _create_picking(self):
        """Skip GRN creation entirely for Work Orders."""
        normal_orders = self.filtered(lambda po: not po.is_work_order)
        if normal_orders:
            return super(PurchaseOrder, normal_orders)._create_picking()
        # For work orders, no GRN should be created at all
        return self.env['stock.picking']