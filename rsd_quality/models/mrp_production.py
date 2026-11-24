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

    @api.depends("qc_quality_check_ids", "qc_quality_check_ids.quality_request_status", "unloading_request_ids.state")
    @api.depends_context("uid")
    def _compute_quality_request_controls(self):
        is_production_user = self.env.user.has_group("mrp.group_mrp_user")
        for production in self:
            accepted = production.is_packing_order or any(req.state == "accepted" for req in production.unloading_request_ids)
            checks = production.sudo().qc_quality_check_ids
            pending_request = checks.filtered(lambda check: check.quality_request_status != "requested")
            production.show_request_quality_button = bool(
                is_production_user
                and accepted
                and checks
                and pending_request
                and production.state not in ("draft", "cancel", "done")
            )

    def action_request_quality(self):
        self.ensure_one()
        if not self.env.user.has_group("mrp.group_mrp_user"):
            raise AccessError(_("Only Production users can request Quality Checks."))

        # Lock the MO row to prevent two users from submitting the same request.
        self.env.cr.execute("SELECT id FROM mrp_production WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset(["qc_quality_check_ids", "unloading_request_ids"])

        if self.state in ("draft", "cancel", "done"):
            raise UserError(_("Quality Checks can only be requested for an active Manufacturing Order."))
        if not self.is_packing_order and not self.unloading_request_ids.filtered(lambda req: req.state == "accepted"):
            raise UserError(_("The Chemist must accept the Unloading Request before Quality Checks can be requested."))

        checks = self.sudo().qc_quality_check_ids
        if not checks:
            raise UserError(_(
                "No Quality Checks exist for this Manufacturing Order. "
                "Please confirm that the applicable Quality Control Points are configured "
                "and that automatic Quality Check generation is enabled."
            ))

        pending_checks = checks.filtered(lambda check: check.quality_request_status != "requested")
        if not pending_checks:
            raise UserError(_("Quality Checks have already been requested for this Manufacturing Order."))

        now = fields.Datetime.now()
        pending_checks.write({
            "quality_request_status": "requested",
            "quality_requested_by": self.env.user.id,
            "quality_requested_on": now,
        })

        # Create one activity on each Quality Check for every Quality Test User.
        # Activities are linked to quality.check, so users can open the exact check
        # directly from My Activities instead of navigating from the MO chatter.
        quality_group = self.env.ref("rsd_quality.group_quality_test_user", raise_if_not_found=False)
        quality_users = quality_group.sudo().users.filtered(lambda user: user.active) if quality_group else self.env["res.users"]
        if not quality_users:
            raise UserError(_(
                "No active users were found in the Quality Test User group. "
                "Please assign Quality users before requesting inspection."
            ))

        activity_type = self.env.ref("mail.mail_activity_data_todo")
        quality_check_model_id = self.env["ir.model"]._get_id("quality.check")
        Activity = self.env["mail.activity"].sudo()
        for check in pending_checks:
            for quality_user in quality_users:
                existing_activity = Activity.search([
                    ("res_model_id", "=", quality_check_model_id),
                    ("res_id", "=", check.id),
                    ("user_id", "=", quality_user.id),
                    ("activity_type_id", "=", activity_type.id),
                    ("summary", "=", "Perform Quality Inspection"),
                ], limit=1)
                if existing_activity:
                    continue
                Activity.create({
                    "activity_type_id": activity_type.id,
                    "summary": "Perform Quality Inspection",
                    "note": _(
                        "Production has requested inspection. Manufacturing Order: %(mo)s. "
                        "Product: %(product)s. Please open this Quality Check and record the inspection result."
                    ) % {
                        "mo": self.display_name,
                        "product": check.product_id.display_name or "-",
                    },
                    "res_model_id": quality_check_model_id,
                    "res_id": check.id,
                    "user_id": quality_user.id,
                    "date_deadline": fields.Date.context_today(self),
                })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Quality Checks Requested"),
                "message": _("Existing Quality Checks have been marked as Requested and the Quality Team has been notified."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_create_unloading_request(self):
        self.ensure_one()
        is_admin = self.env.user.has_group("base.group_system") or self.env.uid == SUPERUSER_ID
        is_supervisor = self.env.user.has_group("rsd_quality.group_unloading_request_supervisor")
        if not (is_admin or is_supervisor):
            raise AccessError(_("Only a Production Supervisor or System Administrator can request unloading."))
        if self.is_packing_order:
            raise UserError(_("Unloading Requests are not required for Packing Instructions."))
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
