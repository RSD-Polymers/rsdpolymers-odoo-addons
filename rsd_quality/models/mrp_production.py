from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    unloading_request_ids = fields.One2many(
        "rsd.quality.unloading.request", "production_id", string="Unloading Requests"
    )
    unloading_request_count = fields.Integer(
        string="Unloading Requests", compute="_compute_unloading_request_count"
    )

    @api.depends("unloading_request_ids")
    def _compute_unloading_request_count(self):
        for production in self:
            production.unloading_request_count = len(production.unloading_request_ids)

    def action_create_unloading_request(self):
        self.ensure_one()
        is_admin = self.env.user.has_group("base.group_system") or self.env.uid == SUPERUSER_ID
        is_supervisor = self.env.user.has_group("rsd_quality.group_unloading_request_supervisor")
        if not (is_admin or is_supervisor):
            raise AccessError(_("Only a Production Supervisor or System Administrator can request unloading."))
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

    def action_view_unloading_requests(self):
        self.ensure_one()
        is_admin = self.env.user.has_group("base.group_system") or self.env.uid == SUPERUSER_ID
        is_supervisor = self.env.user.has_group("rsd_quality.group_unloading_request_supervisor")
        is_chemist = self.env.user.has_group("rsd_quality.group_unloading_request_chemist")
        if not (is_admin or is_supervisor or is_chemist):
            raise AccessError(_("You are not allowed to view unloading requests."))

        requests = self.unloading_request_ids
        if len(requests) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Unloading Request"),
                "res_model": "rsd.quality.unloading.request",
                "view_mode": "form",
                "res_id": requests.id,
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Unloading Requests"),
            "res_model": "rsd.quality.unloading.request",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id},
            "target": "current",
        }
