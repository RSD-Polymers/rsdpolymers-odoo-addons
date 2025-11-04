from email.policy import default

from odoo import models, fields, _, api, exceptions
from datetime import date
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_default_production_request_type(self):
        """
        Dynamically sets the default production request type based on the user's group.
        It defaults to 'trial' for R&D users and 'min_inventory' for others.
        """
        # Check if the current user belongs to the 'R&D' user group.
        if self.env.user.has_group('base.group_research_and_development'):
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
            # 'scale_up' option has been removed
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
        is_rd = self.env.user.has_group('base.group_research_and_development')
        for record in self:
            record.is_rd_user = is_rd

    @api.depends('user_id')
    def _compute_is_production_manager(self):
        """
        Computes if the current user is a member of the Production Manager group.
        """
        for record in self:
            record.is_production_manager = self.env.user.has_group('mrp.group_mrp_manager')

    @api.constrains('mat_ready_date')
    def _check_mat_ready_date_is_future(self):
        for record in self:
            if record.mat_ready_date and record.mat_ready_date < date.today():
                raise exceptions.ValidationError(_("The Material Readiness Date must be a future date."))

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
        """
        Overrides create to set the state and create MOs based on the request type,
        regardless of stock for trial.
        """
        _logger.info("SALES ORDER: CREATE method called.")
        orders = super(SaleOrder, self).create(vals_list)
        for order in orders:
            # Recompute the field to ensure we have the latest value
            order._compute_all_in_stock()

            # The logic for 'scale_up' is now merged with 'trial'
            if order.production_request_type == 'trial':
                _logger.info("SALES ORDER: Trial order %s created. Setting state and creating MO.", order.name)
                order.write({'state': 'trial'})
                order.action_create_mrp_orders()
            elif not order.all_in_stock:
                _logger.warning(
                    "SALES ORDER: Order %s created with out-of-stock items. Setting state to 'awaiting_readiness'.",
                    order.name)
                order.write({'state': 'awaiting_readiness'})
        return orders

    def write(self, values):
        """
        Overrides the standard write method to manage the sales order state
        based on stock availability.
        """
        _logger.info("SALES ORDER: WRITE method called.")
        res = super(SaleOrder, self).write(values)

        for order in self:
            # If the order is a trial, we don't change its state here based on stock
            if order.production_request_type != 'trial':
                if not order.all_in_stock and order.state in ['draft', 'sent']:
                    _logger.warning("SALES ORDER: Order %s has out-of-stock items. Changing state from '%s' to 'awaiting_readiness'.", order.name, order.state)
                    order.state = 'awaiting_readiness'
                elif order.all_in_stock and order.state == 'awaiting_readiness':
                    # If all items are now in stock, revert the state to 'draft'
                    _logger.info("SALES ORDER: All items for order %s are now in stock. Changing state from '%s' to 'draft'.", order.name, order.state)
                    order.state = 'draft'

        return res

    def action_confirm(self):
        """
        Override to extend core validation so our custom states
        can also be confirmed.
        """
        for order in self:
            # Allow extra custom states
            if order.state not in ['draft', 'sent', 'awaiting_readiness', 'trial']:
                raise UserError(_("Some orders are not in a state requiring confirmation."))

            if order.production_request_type == 'trial':
                # Trial request → only MO, no DO/invoice
                _logger.info("SALES ORDER: Trial request detected. Skipping DO/Invoice creation.")
                order.message_post(body=_("This is a trial request. No Delivery Order or Invoice will be created."))
                continue

            # For all other cases → continue with standard confirm logic
            super(SaleOrder, order).action_confirm()

        return True

    def action_create_mrp_orders(self):
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
                })
                _logger.info("SALES ORDER: Created Manufacturing Order %s for product %s.", mo.name, line.product_id.name)

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
        self.invoice_status = 'invoiced'
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