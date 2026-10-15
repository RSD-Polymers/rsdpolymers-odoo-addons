# -*- coding: utf-8 -*-

from odoo import models, fields, _, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # -------------------------------------------------------------------------
    # SALES / DELIVERY INFORMATION
    # -------------------------------------------------------------------------

    all_in_stock = fields.Boolean(
        string="All Products in Stock",
        compute='_compute_all_in_stock',
        store=True,
    )

    delivery_terms = fields.Text(
        string="Terms of Delivery"
    )

    dispatch_through = fields.Char(
        string="Dispatched Through"
    )

    special_instructions = fields.Text(
        string="Special Instructions"
    )

    # -------------------------------------------------------------------------
    # SALES ORDER APPROVAL WORKFLOW
    # -------------------------------------------------------------------------

    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('send_for_checking', 'Send for Checking'),
        ('checked', 'Checked'),
        ('send_for_approval', 'Send for Approval'),
        ('approved', 'Approved'),
    ], default='draft', tracking=True)

    approval_manager_id = fields.Many2one(
        'res.users',
        string="Sales Manager",
        tracking=True,
    )

    checker_id = fields.Many2one(
        'res.users',
        string="Sales Executive-BD (Checker)",
        tracking=True,
    )

    is_sales_manager = fields.Boolean(
        compute="_compute_is_sales_manager",
        store=False,
    )

    rejection_remarks = fields.Text(
        string="Rejection Remarks"
    )

    # -------------------------------------------------------------------------
    # STORE / PACKED FG WORKFLOW
    # -------------------------------------------------------------------------

    is_fully_in_stock = fields.Boolean(
        string="Is Fully In Stock",
        compute="_compute_stock_status",
    )

    has_stock_shortage = fields.Boolean(
        string="Has Stock Shortage",
        compute="_compute_stock_status",
    )

    fg_delivery_mode = fields.Selection([
        ('wait_full', 'Deliver Only When Fully Available'),
        ('partial', 'Deliver Available Quantity Now'),
    ],
        string="FG Delivery Mode",
        default='wait_full',
        tracking=True,
        help=(
            "Controls how the Store team handles delivery of this order's "
            "Packed FG stock:\n"
            "- Deliver Only When Fully Available: wait until all lines can "
            "be fully reserved.\n"
            "- Deliver Available Quantity Now: ship whatever is available "
            "and backorder the rest."
        ),
    )

    store_user = fields.Boolean(
        string="Is Store User",
        compute='_compute_store_user',
        store=False,
        help=(
            "Indicates if the current user belongs to the Store department, "
            "and can therefore reserve/deliver Packed FG stock against this order."
        ),
    )

    # -------------------------------------------------------------------------
    # PRODUCTION DEPARTMENT VISIBILITY
    # -------------------------------------------------------------------------
    #
    # This is retained because the current Sales Order XML uses this field
    # to control visibility of some fields/buttons for Production users.
    #
    # It does NOT control the Production Request workflow itself.
    # Production Request remains in rsd_production.
    # -------------------------------------------------------------------------

    is_production_user_by_dept = fields.Boolean(
        string="Is Production User (by Department)",
        compute='_compute_is_production_user_by_dept',
        store=False,
        help=(
            "Indicates if the current user is in the Production or "
            "Manufacturing department."
        ),
    )

    # =========================================================================
    # STORE USER
    # =========================================================================

    @api.depends_context('uid')
    def _compute_store_user(self):
        user = self.env.user

        is_privileged = (
            user.has_group('base.group_system')
            or user.has_group('stock.group_stock_manager')
        )

        employee = self.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)],
            limit=1,
        )

        is_store = bool(
            employee
            and employee.department_id
            and employee.department_id.name.strip().lower() == 'store'
        )

        for order in self:
            order.store_user = is_privileged or is_store

    # =========================================================================
    # PRODUCTION USER BY DEPARTMENT
    # =========================================================================

    @api.depends('user_id.employee_id.department_id')
    def _compute_is_production_user_by_dept(self):
        for record in self:
            user = self.env.user

            employee = user.employee_id

            department_name = (
                employee.department_id.name.strip().lower()
                if employee and employee.department_id
                else ''
            )

            record.is_production_user_by_dept = department_name in (
                'production',
                'manufacturing',
            )

    # =========================================================================
    # SALES MANAGER
    # =========================================================================

    def _compute_is_sales_manager(self):
        is_manager = self.env.user.has_group(
            'rsd_sales.group_sale_approver'
        )

        for rec in self:
            rec.is_sales_manager = is_manager

    # =========================================================================
    # PACKED FG PICKINGS
    # =========================================================================

    def _get_fg_pickings(self):
        """
        Return outgoing customer deliveries linked to this Sales Order
        that are not yet completed or cancelled.
        """
        self.ensure_one()

        return self.picking_ids.filtered(
            lambda p:
                p.picking_type_id.code == 'outgoing'
                and p.state not in ('done', 'cancel')
        )

    # =========================================================================
    # RESERVE PACKED FG
    # =========================================================================

    def action_reserve_fg(self):
        """
        Reserve available Packed FG stock against the Sales Order's
        outgoing Delivery Order(s).
        """
        for order in self:
            pickings = order._get_fg_pickings()

            if not pickings:
                raise UserError(
                    _(
                        "There is no outgoing delivery to reserve stock "
                        "against for %s."
                    ) % order.name
                )

            pickings.action_assign()

            order.message_post(
                body=_(
                    "Packed FG stock reservation attempted for the "
                    "delivery order(s)."
                )
            )

        return True

    # =========================================================================
    # UNRESERVE PACKED FG
    # =========================================================================

    def action_unreserve_fg(self):
        """
        Release any stock currently reserved against this Sales Order's
        outgoing Delivery Order(s).
        """
        for order in self:
            pickings = order._get_fg_pickings()

            if not pickings:
                raise UserError(
                    _(
                        "There is no outgoing delivery to unreserve "
                        "for %s."
                    ) % order.name
                )

            pickings.do_unreserve()

            order.message_post(
                body=_(
                    "Packed FG stock reservation was released for "
                    "the delivery order(s)."
                )
            )

        return True

    # =========================================================================
    # DELIVER AVAILABLE QUANTITY
    # =========================================================================

    def action_deliver_available(self):
        """
        Deliver whatever Packed FG quantity is currently available.

        Any remaining quantity is handled through Odoo's standard
        backorder process.
        """
        for order in self:
            pickings = order._get_fg_pickings()

            if not pickings:
                raise UserError(
                    _(
                        "There is no outgoing delivery to process "
                        "for %s."
                    ) % order.name
                )

            pickings.action_assign()

            res = pickings.with_context(
                skip_backorder=False
            ).button_validate()

            if (
                isinstance(res, dict)
                and res.get('res_model') == 'stock.backorder.confirmation'
            ):
                wizard = self.env[
                    res['res_model']
                ].with_context(
                    res.get('context', {})
                ).create({})

                wizard.process()

            order.message_post(
                body=_(
                    "Available Packed FG stock was delivered; "
                    "remaining quantity backordered."
                )
            )

        return True

    # =========================================================================
    # WAIT FOR COMPLETE STOCK
    # =========================================================================

    def action_wait_for_complete(self):
        """
        Switch the order back to waiting for full FG availability
        before delivery.
        """
        for order in self:
            order.fg_delivery_mode = 'wait_full'

            order.message_post(
                body=_(
                    "Delivery mode set back to "
                    "'Deliver Only When Fully Available'."
                )
            )

        return True

    # =========================================================================
    # STOCK STATUS
    # =========================================================================

    @api.depends(
        'order_line.product_uom_qty',
        'order_line.product_id',
        'state',
        'approval_state',
    )
    def _compute_stock_status(self):
        """
        Check live Packed - FG availability for the Sales Order.

        This is informational/store-side stock checking only.
        It does NOT block Sales Manager approval.
        """

        packed_loc = self.env['stock.location'].search(
            [('name', '=', 'Packed - FG')],
            limit=1,
        )

        for order in self:

            # Only relevant for normal Odoo Sales Order states.
            if (
                order.state not in ('draft', 'sent', 'sale')
                or not order.order_line
            ):
                order.is_fully_in_stock = False
                order.has_stock_shortage = False
                continue

            all_in_stock = True
            has_storable_lines = False

            for line in order.order_line:

                if (
                    not line.display_type
                    and line.product_id.type == 'consu'
                    and line.product_id.is_storable
                ):
                    has_storable_lines = True

                    if packed_loc:
                        live_qty = (
                            self.env['stock.quant']
                            ._get_available_quantity(
                                line.product_id,
                                packed_loc,
                            )
                        )
                    else:
                        live_qty = 0.0

                    if live_qty < line.product_uom_qty:
                        all_in_stock = False
                        break

            if has_storable_lines:
                order.is_fully_in_stock = all_in_stock
                order.has_stock_shortage = not all_in_stock
            else:
                order.is_fully_in_stock = False
                order.has_stock_shortage = False

    # =========================================================================
    # ALL PRODUCTS IN STOCK
    # =========================================================================

    @api.depends('order_line.is_out_of_stock')
    def _compute_all_in_stock(self):
        """
        Check whether all Sales Order lines are marked as in stock.
        """
        _logger.info(
            "SALES ORDER: _compute_all_in_stock method triggered."
        )

        for order in self:
            is_out_of_stock = any(
                line.is_out_of_stock
                for line in order.order_line
            )

            order.all_in_stock = not is_out_of_stock

            _logger.info(
                "SALES ORDER: Order %s - All in stock status: %s",
                order.name,
                order.all_in_stock,
            )

    # =========================================================================
    # SALES ORDER CONFIRMATION
    # =========================================================================

    def action_confirm(self):
        """
        Confirm the Sales Order using STANDARD ODOO confirmation.

        Custom approval is the only additional condition.

        Once approved, super().action_confirm() handles the normal
        Odoo Sales Order confirmation process, including creation of
        the Delivery Order according to the configured warehouse/routes.
        """

        for order in self:
            if order.approval_state != 'approved':
                raise UserError(
                    _("Order must be approved first.")
                )

        # IMPORTANT:
        # Do not create MOs here.
        # Do not check Material Ready Date here.
        # Do not check Batch/Lot here.
        # Do not handle trial orders here.
        #
        # Standard Odoo confirmation is responsible for the Delivery Order.
        return super().action_confirm()

    # =========================================================================
    # INVOICE PREPARATION
    # =========================================================================

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()

        # Delivery Order information
        picking = self.picking_ids.filtered(
            lambda p: p.state == 'done'
        )[:1]

        if picking:
            vals.update({
                'delivery_note': picking.name,
                'delivery_date': picking.date_done,
            })

        # Sales Order information
        vals.update({
            'ref': self.client_order_ref or self.name or '',
            'dispatch_through': self.dispatch_through or '',
        })

        return vals

    # =========================================================================
    # SEND FOR APPROVAL
    # =========================================================================

    def action_send_for_approval(self):
        """
        Checker sends the checked Sales Order for Manager approval.

        The Checker selects the Sales Manager through the wizard.
        """
        self.ensure_one()

        if self.approval_state != 'checked':
            raise UserError(
                _("Order must be checked before sending for approval.")
            )

        if not self.order_line:
            raise UserError(
                _(
                    "You cannot send an empty order for approval. "
                    "Please add at least one product line."
                )
            )

        return {
            'name': _('Select Sales Manager'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
            },
        }

    # =========================================================================
    # APPROVE ORDER
    # =========================================================================

    def action_approve_order(self):
        """
        Sales Manager approves the Sales Order.

        Approval immediately proceeds to STANDARD ODOO confirmation.
        """

        self.ensure_one()

        if not self.env.user.has_group(
            'rsd_sales.group_sale_approver'
        ):
            raise UserError(
                _(
                    "Only the assigned Sales Manager can "
                    "approve this order."
                )
            )

        if (
            self.approval_manager_id
            and self.env.user.id != self.approval_manager_id.id
        ):
            raise UserError(
                _(
                    "Access Denied: Only %s can approve this order."
                ) % self.approval_manager_id.name
            )

        if self.approval_state != 'send_for_approval':
            raise UserError(
                _("Not waiting for approval.")
            )

        # Mark the custom approval as complete.
        self.approval_state = 'approved'

        # IMPORTANT:
        # This now goes through the standard Odoo Sales Order
        # confirmation workflow.
        self.action_confirm()

        self.message_post(
            body=_(
                "Order approved and confirmed. "
                "Packed FG availability will be handled by Store "
                "after confirmation."
            )
        )

        return True

    # =========================================================================
    # REJECT ORDER
    # =========================================================================

    def action_reject_order(self):
        self.ensure_one()

        if not self.env.user.has_group(
            'rsd_sales.group_sale_approver'
        ):
            raise UserError(
                _(
                    "Only the assigned Sales Manager can "
                    "reject this order."
                )
            )

        if (
            self.approval_manager_id
            and self.env.user.id != self.approval_manager_id.id
        ):
            raise UserError(
                _(
                    "Access Denied: You are not the assigned Sales "
                    "Manager for this order. Only %s can reject it."
                ) % self.approval_manager_id.name
            )

        return {
            'name': _('Reject Order - Provide Remark'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
            },
        }

    # =========================================================================
    # SEND FOR CHECKING
    # =========================================================================

    def action_send_for_checking(self):
        self.ensure_one()

        if self.approval_state != 'draft':
            raise UserError(
                _("Order already sent for checking.")
            )

        if not self.order_line:
            raise UserError(
                _("You cannot send an empty order for checking.")
            )

        return {
            'name': _('Select BDO Checker'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.checker.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
            },
        }

    # =========================================================================
    # CHECKER APPROVES CHECKING
    # =========================================================================

    def action_checker_checked(self):
        self.ensure_one()

        if self.env.user != self.checker_id:
            raise UserError(
                _(
                    "Only the assigned Sales Executive can "
                    "mark this order as Checked."
                )
            )

        if self.approval_state != 'send_for_checking':
            raise UserError(
                _("Order is not waiting for checking.")
            )

        self.approval_state = 'checked'

        return True

    # =========================================================================
    # CHECKER REJECT
    # =========================================================================

    def action_checker_reject(self):
        self.ensure_one()

        if self.approval_state != 'send_for_checking':
            raise UserError(
                _("Order is not waiting for checking.")
            )

        if self.env.user != self.checker_id:
            raise UserError(
                _(
                    "Only the assigned Sales Executive can "
                    "reject this order."
                )
            )

        return {
            'name': _('Reject Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.checker.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
            },
        }