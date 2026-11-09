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
        ("modification_required", "Modification Required"),
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
    analysis_template_id = fields.Many2one("rsd.quality.spec.template", string="Unloading Analysis Format", domain="[('product_id', '=', product_id), ('test_kind', '=', 'unloading'), ('active', '=', True)]", tracking=True)
    analysis_cycle_ids = fields.One2many("rsd.quality.unloading.analysis", "request_id", string="Analysis History", copy=False)
    current_analysis_id = fields.Many2one("rsd.quality.unloading.analysis", compute="_compute_current_analysis", string="Current Analysis")
    modification_description = fields.Text(string="Modification Required")
    modification_done_by = fields.Many2one("res.users", string="Modification Completed By", readonly=True)
    modification_done_on = fields.Datetime(string="Modification Completed On", readonly=True)
    can_submit = fields.Boolean(compute="_compute_permissions")
    can_review = fields.Boolean(compute="_compute_permissions")

    @api.depends("analysis_cycle_ids", "analysis_cycle_ids.cycle_no")
    def _compute_current_analysis(self):
        for request in self:
            cycles = request.analysis_cycle_ids.sorted(lambda c: (c.cycle_no, c.id))
            request.current_analysis_id = cycles[-1] if cycles else False

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
                    ("state", "in", ("draft", "submitted", "accepted", "modification_required")),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "An active unloading request (%s) already exists for this Manufacturing Order."
                    ) % duplicate.display_name)
        return super().create(vals_list)

    def write(self, vals):
        protected = {"name", "production_id", "requested_by", "request_date", "state",
                     "reviewed_by", "reviewed_on", "analysis_cycle_ids", "modification_done_by", "modification_done_on"}
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

    def action_start_analysis(self):
        self.ensure_one()
        self._check_chemist()
        if self.state != "submitted":
            raise UserError(_("Only submitted requests can be analysed."))
        template = self.analysis_template_id or self.env["rsd.quality.spec.template"].search([
            ("product_id", "=", self.product_id.id), ("test_kind", "=", "unloading"),
            ("company_id", "in", [self.company_id.id, False]), ("active", "=", True),
        ], limit=1)
        if not template:
            raise ValidationError(_("Configure an Unloading Analysis template for this product first."))
        if not self.analysis_template_id:
            self.analysis_template_id = template
        pending_cycle = self.analysis_cycle_ids.filtered(lambda cycle: cycle.result == "pending").sorted("cycle_no")[-1:]
        if pending_cycle:
            return {"type": "ir.actions.act_window", "name": _("Unloading Analysis"), "res_model": "rsd.quality.unloading.analysis", "view_mode": "form", "res_id": pending_cycle.id, "target": "current"}
        cycle_no = max(self.analysis_cycle_ids.mapped("cycle_no") or [0]) + 1
        cycle = self.env["rsd.quality.unloading.analysis"].create({
            "request_id": self.id, "cycle_no": cycle_no, "template_id": template.id,
            "analysed_by": self.env.user.id,
            "line_ids": [(0, 0, {"template_line_id": line.id, "sequence": line.sequence}) for line in template.line_ids],
        })
        self.message_post(body=_("Unloading analysis cycle %s started.") % cycle_no)
        return {"type": "ir.actions.act_window", "name": _("Unloading Analysis"), "res_model": "rsd.quality.unloading.analysis", "view_mode": "form", "res_id": cycle.id, "target": "current"}

    def action_complete_modification(self):
        for request in self:
            request._check_supervisor()
            if request.state != "modification_required":
                raise UserError(_("No modification is pending for this request."))
            request._workflow_write({"state": "submitted", "modification_done_by": self.env.user.id, "modification_done_on": fields.Datetime.now()})
            request.message_post(body=_("Physical modification completed by Production. Request resubmitted to QC for a new analysis cycle."))
        return True

    def action_accept(self):
        for request in self:
            request._check_chemist()
            if request.state != "submitted":
                raise UserError(_("Only submitted requests can be accepted."))
            current = request.current_analysis_id
            if not current or current.result != "pass":
                raise ValidationError(_("A passing unloading analysis is required before approval."))
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


class RSDQualityUnloadingAnalysis(models.Model):
    _name = "rsd.quality.unloading.analysis"
    _description = "Unloading Analysis Cycle"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "cycle_no desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    request_id = fields.Many2one("rsd.quality.unloading.request", required=True, ondelete="cascade", index=True)
    cycle_no = fields.Integer(required=True, default=1)
    template_id = fields.Many2one("rsd.quality.spec.template", required=True, ondelete="restrict")
    analysed_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    analysed_on = fields.Datetime(default=fields.Datetime.now, readonly=True)
    line_ids = fields.One2many("rsd.quality.unloading.analysis.line", "analysis_id", copy=True)
    result = fields.Selection([("pending", "Pending"), ("pass", "Pass"), ("fail", "Fail")], default="pending", readonly=True, tracking=True)
    modification_description = fields.Text()
    evaluated_by = fields.Many2one("res.users", readonly=True)
    evaluated_on = fields.Datetime(readonly=True)

    @api.depends("request_id.name", "cycle_no")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s / %s" % (rec.request_id.name or "", rec.cycle_no)

    def action_evaluate(self):
        self.ensure_one()
        self.request_id._check_chemist()
        if self.result != "pending":
            raise UserError(_("This analysis cycle has already been evaluated."))
        if not self.line_ids:
            raise ValidationError(_("The analysis has no parameters."))
        for line in self.line_ids:
            if line.required and not (line.result_value or "").strip():
                raise ValidationError(_("Enter a result for required parameter: %s") % line.name)
        failed = self.line_ids.filtered(lambda line: (line.result_value or "").strip() and not line.is_pass)
        if failed:
            if not (self.modification_description or "").strip():
                raise ValidationError(_("Describe the physical modification required before submitting a failed analysis."))
            self.write({"result": "fail", "evaluated_by": self.env.user.id, "evaluated_on": fields.Datetime.now()})
            self.request_id._workflow_write({"state": "modification_required", "modification_description": self.modification_description, "reviewed_by": self.env.user.id, "reviewed_on": fields.Datetime.now()})
            self.request_id.message_post(body=_("Unloading analysis failed. Production modification required: %s") % self.modification_description)
        else:
            self.write({"result": "pass", "evaluated_by": self.env.user.id, "evaluated_on": fields.Datetime.now()})
            self.request_id._workflow_write({"state": "accepted", "reviewed_by": self.env.user.id, "reviewed_on": fields.Datetime.now(), "modification_description": False})
            self.request_id.message_post(body=_("Unloading analysis passed. Unloading request automatically approved."))
        return True


class RSDQualityUnloadingAnalysisLine(models.Model):
    _name = "rsd.quality.unloading.analysis.line"
    _description = "Unloading Analysis Result"
    _order = "sequence, id"

    analysis_id = fields.Many2one("rsd.quality.unloading.analysis", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    template_line_id = fields.Many2one("rsd.quality.spec.template.line", required=True, ondelete="restrict")
    name = fields.Char(related="template_line_id.name", store=True)
    value_type = fields.Selection(related="template_line_id.value_type", store=True)
    min_value = fields.Float(related="template_line_id.min_value", store=True)
    max_value = fields.Float(related="template_line_id.max_value", store=True)
    expected_text = fields.Char(related="template_line_id.expected_text", store=True)
    uom_id = fields.Many2one(related="template_line_id.uom_id", store=True)
    required = fields.Boolean(related="template_line_id.required", store=True)
    result_value = fields.Char()
    is_pass = fields.Boolean(compute="_compute_is_pass", store=True)

    @api.depends("result_value", "value_type", "min_value", "max_value", "expected_text")
    def _compute_is_pass(self):
        for rec in self:
            value = (rec.result_value or "").strip()
            if rec.value_type == "number":
                try:
                    number = float(value)
                    rec.is_pass = number >= rec.min_value and (not rec.max_value or number <= rec.max_value)
                except (TypeError, ValueError):
                    rec.is_pass = False
            elif rec.value_type == "yes_no":
                rec.is_pass = value.lower() in ("yes", "true", "1")
            else:
                rec.is_pass = value.casefold() == (rec.expected_text or "").strip().casefold()
