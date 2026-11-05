from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class QualityUnloadingRequest(models.Model):
    _name = "rsd.quality.unloading.request"
    _description = "Unloading Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "request_date desc, id desc"

    name = fields.Char(
        string="Request Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"), tracking=True,
    )
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", required=True,
        ondelete="restrict", index=True, tracking=True,
        domain=[("state", "not in", ("draft", "cancel", "done"))],
    )
    product_id = fields.Many2one(
        "product.product", string="Product", related="production_id.product_id",
        store=True, readonly=True,
    )
    product_qty = fields.Float(
        string="MO Quantity", related="production_id.product_qty", readonly=True,
    )
    product_uom_id = fields.Many2one(
        "uom.uom", string="Unit of Measure", related="production_id.product_uom_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company", related="production_id.company_id", store=True, readonly=True,
    )
    requested_by = fields.Many2one(
        "res.users", string="Requested By", required=True,
        default=lambda self: self.env.user, readonly=True, tracking=True,
    )
    request_date = fields.Datetime(
        string="Request Date", required=True, default=fields.Datetime.now,
        readonly=True, tracking=True,
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("submitted", "Waiting for Chemist"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ], string="Status", default="draft", required=True, tracking=True, index=True)
    planned_unloading_datetime = fields.Datetime(
        string="Planned Unloading Date & Time", tracking=True,
    )
    reviewed_by = fields.Many2one(
        "res.users", string="Reviewed By", readonly=True, tracking=True,
    )
    reviewed_on = fields.Datetime(string="Reviewed On", readonly=True, tracking=True)
    rejection_reason = fields.Text(string="Rejection Reason", tracking=True)
    remarks = fields.Text(string="Remarks")
    can_submit = fields.Boolean(compute="_compute_permissions")
    can_review = fields.Boolean(compute="_compute_permissions")

    @api.depends_context("uid")
    def _compute_permissions(self):
        user = self.env.user
        is_admin = user.has_group("base.group_system")
        is_supervisor = user.has_group("rsd_quality.group_unloading_request_supervisor")
        is_chemist = user.has_group("rsd_quality.group_unloading_request_chemist")
        for request in self:
            request.can_submit = is_admin or is_supervisor
            request.can_review = is_admin or is_chemist

    @api.model_create_multi
    def create(self, vals_list):
        self._check_supervisor()
        for vals in vals_list:
            # Never trust caller-supplied ownership, status, review metadata or sequence.
            vals["requested_by"] = self.env.user.id
            vals["request_date"] = fields.Datetime.now()
            vals["state"] = "draft"
            vals["reviewed_by"] = False
            vals["reviewed_on"] = False
            vals["planned_unloading_datetime"] = False
            vals["rejection_reason"] = False
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "rsd.quality.unloading.request"
            ) or _("New")
            production_id = vals.get("production_id")
            if production_id:
                # Serialize requests per MO so two supervisors cannot create
                # duplicate active requests at the same time.
                self.env.cr.execute(
                    "SELECT id FROM mrp_production WHERE id = %s FOR UPDATE",
                    (production_id,),
                )
                production = self.env["mrp.production"].browse(production_id).exists()
                if not production:
                    raise ValidationError(_("Please select a valid Manufacturing Order."))
                if production.state in ("draft", "cancel", "done"):
                    raise ValidationError(_(
                        "An unloading request can only be created for a confirmed, active Manufacturing Order."
                    ))
                duplicate = self.search([
                    ("production_id", "=", production.id),
                    ("state", "in", ("draft", "submitted", "accepted")),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "An active unloading request (%s) already exists for this Manufacturing Order."
                    ) % duplicate.display_name)
        return super().create(vals_list)

    def write(self, vals):
        protected = {"name", "production_id", "requested_by", "request_date", "state",
                     "reviewed_by", "reviewed_on"}
        if protected.intersection(vals):
            raise UserError(_("Use the workflow buttons to update request status and review details."))
        review_fields = {"planned_unloading_datetime", "rejection_reason"}.intersection(vals)
        if review_fields:
            self._check_chemist()
            if any(request.state != "submitted" for request in self):
                raise UserError(_("The unloading plan and rejection reason can only be entered while awaiting Chemist review."))
        if "remarks" in vals:
            for request in self:
                if request.state != "draft":
                    raise UserError(_("Remarks can only be edited while the request is in Draft."))
                request._check_supervisor()
        return super().write(vals)

    def _workflow_write(self, vals):
        # Bypass this model's public write guard only from trusted workflow methods.
        return super(QualityUnloadingRequest, self).write(vals)

    def action_submit(self):
        for request in self:
            request._check_supervisor()
            if request.state != "draft":
                raise UserError(_("Only draft requests can be submitted."))
            if request.production_id.state in ("draft", "cancel", "done"):
                raise UserError(_("The Manufacturing Order must be confirmed and active."))
            request._workflow_write({"state": "submitted"})
            request.message_post(body=_("Unloading request submitted for Production Chemist review."))
        return True

    def action_accept(self):
        for request in self:
            request._check_chemist()
            if request.state != "submitted":
                raise UserError(_("Only submitted requests can be accepted."))
            if not request.planned_unloading_datetime:
                raise ValidationError(_("Enter the planned unloading date and time before accepting."))
            request._workflow_write({
                "state": "accepted",
                "reviewed_by": self.env.user.id,
                "reviewed_on": fields.Datetime.now(),
                "rejection_reason": False,
            })
            request.message_post(body=_("Unloading request accepted. Planned unloading: %s") %
                                 fields.Datetime.to_string(request.planned_unloading_datetime))
        return True

    def action_reject(self):
        for request in self:
            request._check_chemist()
            if request.state != "submitted":
                raise UserError(_("Only submitted requests can be rejected."))
            if not (request.rejection_reason or "").strip():
                raise ValidationError(_("Enter a rejection reason before rejecting the request."))
            reason = request.rejection_reason
            request._workflow_write({
                "state": "rejected", "reviewed_by": self.env.user.id,
                "reviewed_on": fields.Datetime.now(), "planned_unloading_datetime": False,
            })
            request.message_post(body=_("Unloading request rejected. Reason: %s") % reason)
        return True

    def action_reset_to_draft(self):
        for request in self:
            request._check_supervisor()
            if request.state != "rejected":
                raise UserError(_("Only rejected requests can be reset to Draft."))
            request._workflow_write({
                "state": "draft", "rejection_reason": False,
                "planned_unloading_datetime": False, "reviewed_by": False, "reviewed_on": False,
            })
            request.message_post(body=_("Rejected request reset to Draft for correction and resubmission."))
        return True

    def action_cancel(self):
        for request in self:
            request._check_supervisor()
            if request.state not in ("draft", "submitted", "rejected"):
                raise UserError(_("Only Draft, submitted or rejected requests can be cancelled."))
            request._workflow_write({"state": "cancelled"})
            request.message_post(body=_("Unloading request cancelled."))
        return True

    def _check_supervisor(self):
        if not (self.env.user.has_group("base.group_system") or
                self.env.user.has_group("rsd_quality.group_unloading_request_supervisor")):
            raise AccessError(_("This action is restricted to Production Supervisors."))

    def _check_chemist(self):
        if not (self.env.user.has_group("base.group_system") or
                self.env.user.has_group("rsd_quality.group_unloading_request_chemist")):
            raise AccessError(_("This action is restricted to Production Chemists."))
