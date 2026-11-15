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
    has_active_unloading_request = fields.Boolean(compute="_compute_unloading_request_controls")
    show_request_unloading_button = fields.Boolean(compute="_compute_unloading_request_controls")
    quality_check_count = fields.Integer(string="Quality Checks", compute="_compute_quality_check_count")
    show_request_quality_button = fields.Boolean(compute="_compute_quality_request_controls")

    @api.depends("unloading_request_ids")
    def _compute_unloading_request_count(self):
        for production in self:
            production.unloading_request_count = len(production.unloading_request_ids)

    @api.depends("unloading_request_ids.state")
    @api.depends_context("uid")
    def _compute_unloading_request_controls(self):
        active_states = ("draft", "submitted", "accepted", "modification_required")
        is_allowed = (
            self.env.user.has_group("rsd_quality.group_unloading_request_supervisor")
            or self.env.user.has_group("base.group_system")
            or self.env.uid == SUPERUSER_ID
        )
        for production in self:
            active = production.unloading_request_ids.filtered(lambda req: req.state in active_states)
            production.has_active_unloading_request = bool(active)
            production.show_request_unloading_button = bool(
                is_allowed and not active and production.state not in ("draft", "cancel", "done")
            )

    @api.depends("check_ids", "unloading_request_ids.state")
    @api.depends_context("uid")
    def _compute_quality_request_controls(self):
        is_production_user = self.env.user.has_group("mrp.group_mrp_user")
        for production in self:
            accepted = any(req.state == "accepted" for req in production.unloading_request_ids)
            production.show_request_quality_button = bool(
                is_production_user
                and accepted
                and not production.sudo().check_ids
                and production.state not in ("draft", "cancel", "done")
            )

    @api.depends("check_ids")
    def _compute_quality_check_count(self):
        for production in self:
            production.quality_check_count = len(production.sudo().check_ids)

    def action_request_quality(self):
        self.ensure_one()
        if not self.env.user.has_group("mrp.group_mrp_user"):
            raise AccessError(_("Only Production users can request Quality Checks."))
        # Serialize concurrent clicks/requests for the same MO.
        self.env.cr.execute("SELECT id FROM mrp_production WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset(["check_ids", "unloading_request_ids"])
        if self.state in ("draft", "cancel", "done"):
            raise UserError(_("Quality Checks can only be requested for an active Manufacturing Order."))
        if not self.unloading_request_ids.filtered(lambda req: req.state == "accepted"):
            raise UserError(_("The Chemist must accept the Unloading Request before Quality Checks can be requested."))
        if self.sudo().check_ids:
            raise UserError(_("Quality Checks have already been requested or generated for this Manufacturing Order."))
        moves = (self.move_raw_ids | self.move_finished_ids).filtered(lambda move: move.state != "cancel")
        if not moves:
            raise UserError(_("No active Manufacturing stock moves are available to generate Quality Checks."))
        moves.with_context(rsd_quality_manual_request=True)._create_quality_checks_for_mo()
        self.invalidate_recordset(["check_ids"])
        if not self.sudo().check_ids:
            raise UserError(_("No Quality Checks were generated. Please verify the applicable Quality Control Points."))
        self.message_post(body=_("Quality Checks were requested by %s after Unloading Request acceptance.") % self.env.user.display_name)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Quality Checks Requested"),
                "message": _("Standard Quality Checks have been generated for this Manufacturing Order."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_view_quality_checks(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Quality Checks"),
            "res_model": "quality.check",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "context": {"default_production_id": self.id},
            "target": "current",
        }

    def action_create_unloading_request(self):
        self.ensure_one()
        is_admin = self.env.user.has_group("base.group_system") or self.env.uid == SUPERUSER_ID
        is_supervisor = self.env.user.has_group("rsd_quality.group_unloading_request_supervisor")
        if not (is_admin or is_supervisor):
            raise AccessError(_("Only a Production Supervisor or System Administrator can request unloading."))
        if self.state in ("draft", "cancel", "done"):
            raise UserError(_("An unloading request can only be created for a confirmed, active Manufacturing Order."))
        if self.unloading_request_ids.filtered(lambda req: req.state in ("draft", "submitted", "accepted", "modification_required")):
            raise UserError(_("An active Unloading Request already exists for this Manufacturing Order."))
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
