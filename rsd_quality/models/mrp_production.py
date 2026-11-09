from odoo import fields, models, _, api
from odoo.exceptions import AccessError, UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    unloading_request_ids = fields.One2many(
        "rsd.quality.unloading.request", "production_id", string="Unloading Requests"
    )

    def action_create_unloading_request(self):
        self.ensure_one()
        if not self.env.user.has_group("rsd_quality.group_unloading_request_supervisor"):
            raise AccessError(_("Only a Production Supervisor can request unloading."))
        if self.state in ("draft", "cancel", "done"):
            raise UserError(_("An unloading request can only be created for a confirmed, active Manufacturing Order."))
        return {
            "type": "ir.actions.act_window",
            "name": _("New Unloading Request"),
            "res_model": "rsd.quality.unloading.request",
            "view_mode": "form",
            "views": [(self.env.ref("rsd_quality.quality_unloading_request_view_form").id, "form")],
            "target": "current",
            "context": {"default_production_id": self.id},
        }
