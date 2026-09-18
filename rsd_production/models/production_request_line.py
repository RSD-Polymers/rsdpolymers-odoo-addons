# rsd_production/models/production_request_line.py

# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ProductionRequestLine(models.Model):
    _name = "production.request.line"
    _description = "Production Request Line"
    _order = "id"

    request_id = fields.Many2one(
        "production.request",
        string="Production Request",
        required=True,
        ondelete="cascade",
        index=True,
    )

    sale_line_id = fields.Many2one(
        "sale.order.line",
        string="Sales Order Line",
        index=True,
    )

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        index=True,
    )

    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Unit of Measure",
        required=True,
    )

    sales_required_qty = fields.Float(
        string="Sales Required Qty",
        digits="Product Unit of Measure",
    )

    fg_available_qty = fields.Float(
        string="FG Available Qty",
        digits="Product Unit of Measure",
    )

    required_qty = fields.Float(
        string="Required Qty",
        required=True,
        digits="Product Unit of Measure",
        help="Quantity that Production needs to manufacture/pack.",
    )

    company_id = fields.Many2one(
        related="request_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )

    mo_ids = fields.One2many(
        "mrp.production",
        "production_request_line_id",
        string="Manufacturing Orders",
        domain=[("is_packing_order", "=", False)],
    )

    pi_ids = fields.One2many(
        "mrp.production",
        "production_request_line_id",
        string="Packing Instructions",
        domain=[("is_packing_order", "=", True)],
    )

    mo_qty = fields.Float(
        string="MO Qty",
        compute="_compute_execution_qty",
        digits="Product Unit of Measure",
        store=True,
    )

    pi_qty = fields.Float(
        string="PI Qty",
        compute="_compute_execution_qty",
        digits="Product Unit of Measure",
        store=True,
    )

    allocated_qty = fields.Float(
        string="Allocated / Fulfilled Qty",
        compute="_compute_execution_qty",
        digits="Product Unit of Measure",
        store=True,
    )

    remaining_qty = fields.Float(
        string="Remaining Qty",
        compute="_compute_execution_qty",
        digits="Product Unit of Measure",
        store=True,
    )

    execution_count = fields.Integer(
        string="Execution Documents",
        compute="_compute_execution_count",
    )

    mo_count = fields.Integer(
        string="MO Count",
        compute="_compute_execution_count",
    )

    pi_count = fields.Integer(
        string="PI Count",
        compute="_compute_execution_count",
    )

    @api.depends(
        "required_qty",
        "mo_ids.product_qty",
        "mo_ids.product_uom_id",
        "mo_ids.state",
        "mo_ids.is_packing_order",
        "pi_ids.product_qty",
        "pi_ids.product_uom_id",
        "pi_ids.state",
    )
    def _compute_execution_qty(self):
        for line in self:
            mo_qty = 0.0
            pi_qty = 0.0

            for mo in line.mo_ids:
                if mo.state == "cancel":
                    continue

                qty = mo.product_qty

                if mo.product_uom_id != line.product_uom_id:
                    qty = mo.product_uom_id._compute_quantity(
                        qty,
                        line.product_uom_id,
                    )

                mo_qty += qty

            for pi in line.pi_ids:
                if pi.state == "cancel":
                    continue

                qty = pi.product_qty

                if pi.product_uom_id != line.product_uom_id:
                    qty = pi.product_uom_id._compute_quantity(
                        qty,
                        line.product_uom_id,
                    )

                pi_qty += qty

            allocated_qty = mo_qty + pi_qty

            line.mo_qty = mo_qty
            line.pi_qty = pi_qty
            line.allocated_qty = allocated_qty
            line.remaining_qty = max(
                line.required_qty - allocated_qty,
                0.0,
            )

    @api.depends("mo_ids", "pi_ids")
    def _compute_execution_count(self):
        for line in self:
            mo_ids = line.mo_ids
            pi_ids = line.pi_ids

            line.mo_count = len(mo_ids)
            line.pi_count = len(pi_ids)
            line.execution_count = len(mo_ids | pi_ids)

    @api.constrains("required_qty")
    def _check_required_qty(self):
        for line in self:
            if line.required_qty <= 0:
                raise ValidationError(
                    _("Required quantity must be greater than zero.")
                )

    @api.constrains("product_uom_id", "product_id")
    def _check_product_uom(self):
        for line in self:
            if not line.product_id or not line.product_uom_id:
                continue

            if line.product_uom_id.category_id != line.product_id.uom_id.category_id:
                raise ValidationError(
                    _(
                        "The Unit of Measure '%s' is not compatible with "
                        "product '%s'."
                    )
                    % (
                        line.product_uom_id.display_name,
                        line.product_id.display_name,
                    )
                )

    def _check_can_create_execution(self):
        self.ensure_one()

        if self.request_id.state != "accepted":
            raise UserError(
                _(
                    "The Production Request must be accepted before "
                    "creating Manufacturing Orders or Packing Instructions."
                )
            )

        if self.remaining_qty <= 0:
            raise UserError(
                _("There is no remaining quantity for this Production Request line.")
            )

        if not self.product_id:
            raise UserError(_("Product is required."))

    def action_create_mo(self):
        self.ensure_one()
        self._check_can_create_execution()

        return {
            "type": "ir.actions.act_window",
            "name": _("Create Manufacturing Order"),
            "res_model": "production.request.execution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_line_id": self.id,
                "default_execution_type": "mo",
                "default_quantity": self.remaining_qty,
            },
        }

    def action_create_pi(self):
        self.ensure_one()
        self._check_can_create_execution()

        return {
            "type": "ir.actions.act_window",
            "name": _("Create Packing Instruction"),
            "res_model": "production.request.execution.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_line_id": self.id,
                "default_execution_type": "pi",
                "default_quantity": self.remaining_qty,
            },
        }

    def action_view_mos(self):
        self.ensure_one()

        action = self.env.ref(
            "mrp.mrp_production_action"
        ).read()[0]

        action["domain"] = [
            ("production_request_line_id", "=", self.id),
            ("is_packing_order", "=", False),
        ]

        return action

    def action_view_pis(self):
        self.ensure_one()

        action = self.env.ref(
            "mrp.mrp_production_action"
        ).read()[0]

        action["domain"] = [
            ("production_request_line_id", "=", self.id),
            ("is_packing_order", "=", True),
        ]

        return action

    def _sync_request_state(self):
        for line in self:
            if line.request_id:
                line.request_id._sync_state_from_lines()