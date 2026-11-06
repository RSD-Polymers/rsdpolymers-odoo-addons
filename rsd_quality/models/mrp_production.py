from odoo import fields, models, _
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    unloading_request_ids = fields.One2many(
        "rsd.quality.unloading.request",
        "production_id",
        string="Unloading Requests",
    )

    unloading_request_count = fields.Integer(
        string="Unloading Requests",
        compute="_compute_unloading_request_count",
    )

    def _compute_unloading_request_count(self):
        request_model = self.env[
            "rsd.quality.unloading.request"
        ].sudo()

        for production in self:
            production.unloading_request_count = request_model.search_count([
                ("production_id", "=", production.id)
            ])


    inprocess_test_count = fields.Integer(
        string="In-Process Tests",
        compute="_compute_inprocess_test_count",
    )

    def _compute_inprocess_test_count(self):
        test_model = self.env["rsd.quality.inprocess.test"].sudo()
        for production in self:
            production.inprocess_test_count = test_model.search_count([
                ("production_id", "=", production.id),
            ])

    def action_create_inprocess_test(self):
        self.ensure_one()
        if self.state in ("draft", "cancel", "done"):
            raise UserError(_(
                "An In-Process Test can only be created for a confirmed, active Manufacturing Order."
            ))
        return {
            "type": "ir.actions.act_window",
            "name": _("New In-Process Test"),
            "res_model": "rsd.quality.inprocess.test",
            "view_mode": "form",
            "views": [(
                self.env.ref("rsd_quality.inprocess_test_view_form").id,
                "form",
            )],
            "target": "current",
            "context": {"default_production_id": self.id},
        }

    def action_view_inprocess_tests(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("In-Process Tests"),
            "res_model": "rsd.quality.inprocess.test",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id},
        }

    def action_create_unloading_request(self):
        self.ensure_one()

        if self.state in ("draft", "cancel", "done"):
            raise UserError(_(
                "An unloading request can only be created for a "
                "confirmed, active Manufacturing Order."
            ))

        return {
            "type": "ir.actions.act_window",
            "name": _("New Unloading Request"),
            "res_model": "rsd.quality.unloading.request",
            "view_mode": "form",
            "views": [(
                self.env.ref(
                    "rsd_quality.quality_unloading_request_view_form"
                ).id,
                "form",
            )],
            "target": "current",
            "context": {
                "default_production_id": self.id,
            },
        }

    def action_view_unloading_requests(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Unloading Requests"),
            "res_model": "rsd.quality.unloading.request",
            "view_mode": "list,form",
            "domain": [
                ("production_id", "=", self.id),
            ],
            "context": {
                "default_production_id": self.id,
            },
        }