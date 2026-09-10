from email.policy import default

from odoo import models, fields, _, api, exceptions
from datetime import date
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_default_production_request_type(self):
        """\
        Dynamically sets the default production request type based on the user's group.
        It defaults to 'trial' for R&D users and 'min_inventory' for others.
        """
        # Check if the current user belongs to the 'R&D' user group.
        if self.env.user.has_group('rsd_sales.group_rd_user'):
            return 'trial'  # Changed from 'scale_up' to 'trial'
        else:
            return 'min_inventory'

    state = fields.Selection(selection_add=[
        ('awaiting_readiness', 'Awaiting Readiness'),
        ('trial', 'Trial'),
    ], ondelete={'awaiting_readiness': 'set default', 'trial': 'set default'})

    all_in_stock = fields.Boolean(
        string="All Products in Stock",
        compute='_compute_all_in_stock',
        store=True,
    )

    mat_ready_date = fields.Date(
        string="Material Readiness Date",
        tracking=True,
        help="Date when the material is ready. Should be added by production co-ordinator"
    )

    dispatch_date = fields.Date(
        string="Scheduled Dispatch Date",
        help="Date when the dispatch of material is scheduled"
    )

    mrp_production_ids = fields.One2many('mrp.production', 'origin_sale_id', string='Manufacturing Orders')

    mrp_order_count = fields.Integer(
        string="Manufacturing Order Count",
        compute='_compute_mrp_order_count'
    )

    production_request_type = fields.Selection(
        selection=[
            ('min_inventory', 'Minimum Inventory Level'),
            ('trial', 'Trial for Process Development'),
            ('order', 'Customer Order'),
        ],
        string="Type Of Production Request",
        default=_get_default_production_request_type,
        help="Type of production request from the sales department."
    )

    is_production_manager = fields.Boolean(
        string="Is Production Manager",
        compute='_compute_is_production_manager',
        store=False,
        help="Indicates if the current user is a Production Manager."
    )

    is_production_request_sent = fields.Boolean(
        string="In Production Request Sent",
        store=True,
        default=False,
    )

    is_rd_user = fields.Boolean(
        string="Is R&D User",
        compute='_compute_is_rd_user',
        store=False,
    )

    is_production_user_by_dept = fields.Boolean(
        string="Is Production User (by Department)",
        compute='_compute_is_production_user_by_dept',
        store=False,
        help="Indicates if the current user is in the Production or Manufacturing department."
    )
    delivery_terms = fields.Text(string="Terms of Delivery")
    dispatch_through = fields.Char(string="Dispatched Through")

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
        tracking=True
    )

    checker_id = fields.Many2one(
        'res.users',
        string="Sales Executive-BD (Checker)",
        tracking=True
    )

    is_sales_manager = fields.Boolean(
        compute="_compute_is_sales_manager",
        store=False
    )

    rejection_remarks = fields.Text(string="Rejection Remarks")

    is_fully_in_stock = fields.Boolean(
        string="Is Fully In Stock",
        compute="_compute_stock_status"
    )

    has_stock_shortage = fields.Boolean(
        string="Has Stock Shortage",
        compute="_compute_stock_status"
    )

    special_instructions = fields.Text(string="Special Instructions")

    fg_delivery_mode = fields.Selection([
        ('wait_full', 'Deliver Only When Fully Available'),
        ('partial', 'Deliver Available Quantity Now'),
    ], string="FG Delivery Mode", default='wait_full', tracking=True,
        help="Controls how the Store team handles delivery of this order's Packed FG stock:\n"
             "- Deliver Only When Fully Available: wait until all lines can be fully reserved.\n"
             "- Deliver Available Quantity Now: ship whatever is available and backorder the rest.")

    store_user = fields.Boolean(
        string="Is Store User",
        compute='_compute_store_user',
        store=False,
        help="Indicates if the current user belongs to the Store department, and can therefore "
             "reserve/deliver Packed FG stock against this order.",
    )

    @api.depends_context('uid')
    def _compute_store_user(self):
        user = self.env.user
        is_privileged = user.has_group('base.group_system') or user.has_group('stock.group_stock_manager')
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        is_store = bool(employee and employee.department_id and employee.department_id.name.strip().lower() == 'store')
        for order in self:
            order.store_user = is_privileged or is_store

    def _get_fg_pickings(self):
        """Outgoing (customer) pickings linked to this order that are not yet done/cancelled."""
        self.ensure_one()
        return self.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing' and p.state not in ('done', 'cancel')
        )

    def action_reserve_fg(self):
        """Reserve available Packed FG stock against this order's outgoing delivery(ies)."""
        for order in self:
            pickings = order._get_fg_pickings()
            if not pickings:
                raise UserError(_("There is no outgoing delivery to reserve stock against for %s.") % order.name)
            pickings.action_assign()
            order.message_post(body=_("Packed FG stock reservation attempted for the delivery order(s)."))
        return True

    def action_unreserve_fg(self):
        """Release any stock currently reserved against this order's outgoing delivery(ies)."""
        for order in self:
            pickings = order._get_fg_pickings()
            if not pickings:
                raise UserError(_("There is no outgoing delivery to unreserve for %s.") % order.name)
            pickings.do_unreserve()
            order.message_post(body=_("Packed FG stock reservation was released for the delivery order(s)."))
        return True

    def action_deliver_available(self):
        """
        Validate the delivery for whatever quantity is currently reserved/available,
        creating a backorder for anything short. Intended for use when
        fg_delivery_mode = 'partial'.
        """
        for order in self:
            pickings = order._get_fg_pickings()
            if not pickings:
                raise UserError(_("There is no outgoing delivery to process for %s.") % order.name)
            pickings.action_assign()
            # Allow a backorder to be created automatically for whatever isn't available yet.
            res = pickings.with_context(skip_backorder=False).button_validate()
            if isinstance(res, dict) and res.get('res_model') == 'stock.backorder.confirmation':
                # Core wizard needs an explicit confirmation to create the backorder.
                wizard = self.env[res['res_model']].with_context(res.get('context', {})).create({})
                wizard.process()
            order.message_post(body=_("Available Packed FG stock was delivered; remaining quantity backordered."))
        return True

    def action_wait_for_complete(self):
        """Switch the order back to waiting for full FG availability before delivering."""
        for order in self:
            order.fg_delivery_mode = 'wait_full'
            order.message_post(body=_("Delivery mode set back to 'Deliver Only When Fully Available'."))
        return True

    @api.depends('order_line.product_uom_qty', 'order_line.product_id', 'state', 'approval_state')
    def _compute_stock_status(self):
        # Fetch the location once outside the loop to keep the system fast
        packed_loc = self.env['stock.location'].search([
            ('name', '=', 'Packed - FG')
        ], limit=1)

        for order in self:
            if (order.state not in ['draft', 'sent', 'awaiting_readiness', 'trial', 'sale'] or
                    not order.order_line):
                order.is_fully_in_stock = False
                order.has_stock_shortage = False
                continue

            all_in_stock = True
            has_storable_lines = False

            for line in order.order_line:
                if not line.display_type and line.product_id.type == 'consu' and line.product_id.is_storable:
                    has_storable_lines = True

                    # Perform a real-time LIVE query on the database for this specific product
                    if packed_loc:
                        # _get_available_quantity calculates On Hand MINUS Reserved.
                        # This prevents approving orders when the stock is already promised to someone else!
                        live_qty = self.env['stock.quant']._get_available_quantity(
                            line.product_id,
                            packed_loc
                        )
                    else:
                        live_qty = 0.0

                    if live_qty < line.product_uom_qty:
                        all_in_stock = False
                        break  # Stop checking if we find even one shortage

            # Set the fields based on what we found in the live database
            if has_storable_lines:
                order.is_fully_in_stock = all_in_stock
                order.has_stock_shortage = not all_in_stock
            else:
                order.is_fully_in_stock = False
                order.has_stock_shortage = False

    def _compute_is_sales_manager(self):
        for rec in self:
            rec.is_sales_manager = self.env.user.has_group(
                'rsd_sales.group_sale_approver'
            )

    def _confirmation_error_message(self):
        """
        Extends the core method to allow confirmation from the 'awaiting_readiness' state.
        """
        self.ensure_one()

        # --- MODIFICATION START ---
        # Add 'awaiting_readiness' to the list of allowed states
        ALLOWED_STATES = {'draft', 'sent', 'awaiting_readiness'}

        if self.state not in ALLOWED_STATES:
            # You can return the original error message or a more specific one
            return _("Some orders are not in a state requiring confirmation.")
            # --- MODIFICATION END ---

        # The rest of the original logic to check for missing products should remain.
        if any(
                not line.display_type
                and not line.is_downpayment
                and not line.product_id
                for line in self.order_line
        ):
            return _("A line on these orders missing a product, you cannot confirm it.")

        return False

    @api.depends('user_id.employee_id.department_id')
    def _compute_is_production_user_by_dept(self):
        """
        Checks if the user's department is 'Production' or 'Manufacturing'
        to control UI visibility.
        """
        for record in self:
            user_department_name = record.env.user.employee_id.department_id.name
            if user_department_name in ['Production', 'Manufacturing']:
                record.is_production_user_by_dept = True
            else:
                record.is_production_user_by_dept = False

    @api.depends('user_id')
    def _compute_is_rd_user(self):
        """
        Computes whether the current user belongs to the R&D group.
        """
        is_rd = self.env.user.has_group('rsd_sales.group_rd_user')
        for record in self:
            record.is_rd_user = is_rd

    @api.depends('user_id')
    def _compute_is_production_manager(self):
        """
        Computes if the current user is a member of the Production Manager group.
        """
        for record in self:
            record.is_production_manager = self.env.user.has_group('mrp.group_mrp_manager')

    @api.constrains('mat_ready_date', 'dispatch_date', 'commitment_date')
    def _check_date_validations(self):
        for record in self:

            # 1️⃣ Material Readiness must be future
            if record.mat_ready_date:
                if record.mat_ready_date <= date.today():
                    raise ValidationError(
                        _("Material Readiness Date must be a future date.")
                    )

            # 2️⃣ Dispatch Date > Material Readiness Date
            if record.mat_ready_date and record.dispatch_date:
                if record.dispatch_date <= record.mat_ready_date:
                    raise ValidationError(
                        _("Scheduled Dispatch Date must be after the Material Readiness Date.")
                    )

            # 3️⃣ Delivery Date > Dispatch Date
            if record.dispatch_date and record.commitment_date:
                delivery_date = record.commitment_date.date()

                if delivery_date <= record.dispatch_date:
                    raise ValidationError(
                        _("Delivery Date must be after the Scheduled Dispatch Date.")
                    )

    def _compute_mrp_order_count(self):
        """
        Computes the number of Manufacturing Orders linked to this sales order.
        """
        for order in self:
            order.mrp_order_count = self.env['mrp.production'].search_count(
                [('origin_sale_id', '=', order.id)]
            )

    @api.depends('order_line.is_out_of_stock')
    def _compute_all_in_stock(self):
        """ Checks if all products in the sales order lines are in stock. """
        _logger.info("SALES ORDER: _compute_all_in_stock method triggered.")
        for order in self:
            is_out_of_stock = any(line.is_out_of_stock for line in order.order_line)
            order.all_in_stock = not is_out_of_stock
            _logger.info("SALES ORDER: Order %s - All in stock status: %s", order.name, order.all_in_stock)

    @api.model_create_multi
    def create(self, vals_list):

        _logger.info("SALES ORDER: CREATE method called.")
        orders = super(SaleOrder, self).create(vals_list)

        for order in orders:

            if order.production_request_type == 'trial':
                _logger.info(
                    "SALES ORDER: Trial order %s created. Setting state and creating MO.",
                    order.name
                )
                order.write({'state': 'trial'})
                order.action_create_mrp_orders()

        return orders

    def write(self, values):

        _logger.info("SALES ORDER: WRITE method called.")
        res = super(SaleOrder, self).write(values)

        return res

    def action_confirm(self):
        """
        Override to extend core validation so our custom states
        can also be confirmed.
        """

        for order in self:
            # 1. Approval check
            if order.approval_state != 'approved':
                raise UserError(_("Order must be approved first"))
            # 2. State check
            if order.state not in ['draft', 'sent', 'awaiting_readiness', 'trial']:
                raise UserError(_("Some orders are not in a state requiring confirmation."))
            # 3. Batch check
            # for line in order.order_line:
            #     if not line.display_type and line.product_id and line.product_id.type == 'consu' and not line.lot_ids:
            #         raise UserError(_(
            #             "Please select Batch No. for product '%s' before confirming the order."
            #         ) % line.product_id.display_name)

        trial_orders = self.filtered(lambda o: o.production_request_type == 'trial')
        normal_orders = self - trial_orders

        # Handle trial orders separately
        for order in trial_orders:
            _logger.info("SALES ORDER: Trial request detected. Skipping DO/Invoice creation.")
            order.message_post(
                body=_("This is a trial request. No Delivery Order or Invoice will be created.")
            )

        # Confirm normal orders using standard Odoo flow
        if normal_orders:
            super(SaleOrder, normal_orders).action_confirm()

        return True

    def _action_create_mrp_orders_from_wizard(self, is_packing_order=False):
        return self.action_create_mrp_orders(is_packing_order=is_packing_order)

    def action_create_mrp_orders(self, is_packing_order=False):
        """
        Creates Manufacturing Orders for products on the sales order.
        For trials, it creates for all lines. For standard orders, it's for out-of-stock.
        """
        _logger.info("SALES ORDER: action_create_mrp_orders triggered.")
        for order in self:
            # Determine which lines to create MOs for
            if order.production_request_type == 'trial':
                # Filter for products that can be manufactured (product or consumable)
                lines_to_process = order.order_line.filtered(lambda l: l.product_id.type in ('product', 'consu'))
                _logger.info("SALES ORDER: lines_to_process for trial: %s", lines_to_process.mapped('product_id.name'))
            else:
                if not order.mat_ready_date:
                    raise UserError(
                        _("Please set the Material Readiness Date before creating a Manufacturing Order.")
                    )
                lines_to_process = order.order_line.filtered(lambda l: l.is_out_of_stock and l.product_id.type in ('product', 'consu'))
                _logger.info("SALES ORDER: lines_to_process for min_inventory: %s", lines_to_process.mapped('product_id.name'))

            if not lines_to_process:
                _logger.warning("SALES ORDER: No manufacturable products found for order %s. Skipping MO creation.", order.name)
                self.is_production_request_sent = True
                continue  # Skip to the next order in the loop

            for line in lines_to_process:
                boms = self.env['mrp.bom']._bom_find(products=line.product_id, company_id=line.company_id.id)
                bom = boms[line.product_id]
                if not bom:
                    raise UserError(_("No Bill of Materials found for product %s.") % line.product_id.name)

                mo = self.env['mrp.production'].create({
                    'product_id': line.product_id.id,
                    'product_qty': line.product_uom_qty,
                    'product_uom_id': line.product_uom.id,
                    'bom_id': bom.id,
                    'origin': order.name,
                    'company_id': order.company_id.id,
                    'origin_sale_id': order.id,
                    'production_request_type': order.production_request_type,
                    'is_packing_order': is_packing_order,
                })
                _logger.info("SALES ORDER: Created Manufacturing Order %s for product %s.", mo.name, line.product_id.name, is_packing_order)

        # Add the chatter message
        self.message_post(
            body=_("Manufacturing Orders have been created."),
            subtype_xmlid="mail.mt_note"
        )

        self.is_production_request_sent = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_confirm_from_readiness(self):
        """
        This button is for a manager to confirm the order after the MOs are complete.
        """
        _logger.info("SALES ORDER: action_confirm_from_readiness method called.")
        self.ensure_one()
        if not self.mat_ready_date:
            raise UserError(_("Please set a Material Readiness Date before confirming."))
        if self.state not in ('awaiting_readiness', 'trial'):
            raise UserError(
                _("The order state must be 'Awaiting Readiness' or 'Trial' to confirm from this action."))
        # Check if all related manufacturing orders are completed.
        for order in self:
            # Use linked MOs OR fallback to origin-based search
            mos = order.mrp_production_ids or self.env['mrp.production'].search([('origin', '=', order.name)])
            for mo in mos:
                if mo.state != 'done':
                    raise UserError(_(
                        "Please ensure all Manufacturing Orders linked to this Sales Order are completed & Products are available in Stock."
                    ))

        self.action_confirm()

        self.state = 'sale'
        self.message_post(body=_("Order confirmed by manager after readiness check."))

        return True

    def action_view_mrp_orders(self):
        """
        Returns a window action to display all linked Manufacturing Orders
        by searching for MOs that have this sales order's name in their `origin` field.
        """
        _logger.info("SALES ORDER: action_view_mrp_orders method called.")
        self.ensure_one()

        # Find all MOs that have this SO's name as their origin
        mrp_orders = self.env['mrp.production'].search([('origin', '=', self.name)])

        return {
            'name': _('Manufacturing Orders'),
            'view_mode': 'list,form',
            'res_model': 'mrp.production',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', mrp_orders.ids)],
            'context': {'create': False},
        }

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()

        # --- Delivery Order ---
        picking = self.picking_ids.filtered(lambda p: p.state == 'done')[:1]

        if picking:
            vals.update({
                'delivery_note': picking.name,
                'delivery_date': picking.date_done,
            })

        # --- From Sales Order ---
        vals.update({
            'ref': self.client_order_ref or self.name or '',
            'dispatch_through': self.dispatch_through or '',
        })

        return vals

    def action_send_for_approval(self):
        self.ensure_one()

        if self.approval_state != 'checked':
            raise UserError(_("Order must be checked before sending for approval"))

        if not self.order_line:
            raise UserError(_("You cannot send an empty order for approval. Please add at least one product line."))

        # Return the action to open the wizard
        return {
            'name': _('Select Sales Manager'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_approve_order(self):
        self.ensure_one()

        if not self.env.user.has_group('rsd_sales.group_sale_approver'):
            raise UserError(_("Only the assigned Sales Manager can approve this order."))

        if self.approval_manager_id and self.env.user.id != self.approval_manager_id.id:
            raise UserError(_(
                "Access Denied: Only %s can approve this order."
            ) % self.approval_manager_id.name)

        if self.approval_state != 'send_for_approval':
            raise UserError(_("Not waiting for approval"))

        # Approval is independent of FG availability.
        # The Store/Production workflow starts after SO confirmation.
        self.approval_state = 'approved'
        self.action_confirm()
        self.message_post(body=_(
            "Order approved and confirmed. Packed FG availability will be handled by Store after confirmation."
        ))
        return True

    def action_reject_order(self):
        self.ensure_one()
        # Security check: ensure only managers can trigger the wizard
        if not self.env.user.has_group('rsd_sales.group_sale_approver'):
            raise UserError(_("Only the assigned Sales Manager can reject this order."))

        if self.approval_manager_id and self.env.user.id != self.approval_manager_id.id:
            raise UserError(_(
                "Access Denied: You are not the assigned Sales Manager for this order. "
                "Only %s can reject it."
            ) % self.approval_manager_id.name)

        return {
            'name': _('Reject Order - Provide Remark'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_send_for_checking(self):

        self.ensure_one()

        if self.approval_state != 'draft':
            raise UserError(_("Order already sent for checking"))

        if not self.order_line:
            raise UserError(_("You cannot send an empty order for checking."))

        return {
            'name': _('Select BDO Checker'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.checker.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_checker_checked(self):
        self.ensure_one()

        if self.env.user != self.checker_id:
            raise UserError(_("Only the assigned Sales Executive can mark this order as Checked."))

        if self.approval_state != 'send_for_checking':
            raise UserError(_("Order is not waiting for checking"))

        self.approval_state = 'checked'

    def action_checker_reject(self):
        self.ensure_one()

        if self.approval_state != 'send_for_checking':
            raise UserError(_("Order is not waiting for checking"))

        if self.env.user != self.checker_id:
            raise UserError(_("Only the assigned Sales Executive can reject this order."))

        return {
            'name': _('Reject Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.checker.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }