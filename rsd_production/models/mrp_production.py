from odoo import models, fields, api
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    tare_weight = fields.Float("Tare Weight (KG)")

    packed_by = fields.Many2one(
        "res.users",
        string="Packed By"
    )

    prepared_by = fields.Many2one(
        "res.users",
        string="Prepared By",
        default=lambda self: self.env.user,
        readonly=True
    )

    rm_issue_status = fields.Selection([
        ('not_requested', 'Not Requested'),
        ('requested', 'Waiting RM Issue'),
        ('issued', 'RM Issued')
    ], default='not_requested', tracking=True)

    show_request_rm_button = fields.Boolean(
        compute="_compute_show_request_rm_button"
    )

    show_issue_rm_button = fields.Boolean(
        compute="_compute_show_issue_rm_button"
    )

    def _compute_prepared_by(self):
        for rec in self:
            rec.prepared_by = rec.create_uid.name

    @api.depends('state', 'product_qty', 'qty_producing', 'rm_issue_status', 'is_packing_order')
    def _compute_show_produce(self):

        super()._compute_show_produce()

        for production in self:

            # Block production until RM is issued
            if production.rm_issue_status != 'issued':
                production.show_produce = False
                production.show_produce_all = False

    def _compute_show_request_rm_button(self):
        for rec in self:
            user = self.env.user

            if user.employee_id and user.employee_id.department_id:
                rec.show_request_rm_button = (
                        user.employee_id.department_id.name == "Production"
                )
            else:
                rec.show_request_rm_button = False

    def _compute_show_issue_rm_button(self):
        for rec in self:
            user = self.env.user

            if user.employee_id and user.employee_id.department_id:
                rec.show_issue_rm_button = (
                        user.employee_id.department_id.name == "Store"
                )
            else:
                rec.show_issue_rm_button = False

    # -----------------------------------------------------
    # RM ISSUE REQUEST (Production → Store)
    # -----------------------------------------------------

    def action_request_rm_issue(self):

        for mo in self:

            if mo.is_packing_order:
                continue

            if mo.state not in ('confirmed', 'progress'):
                raise UserError("RM Issue Request can only be sent after confirming the MO.")

            mo.rm_issue_status = 'requested'

            body = f"""
                <p>Hello Store Team,</p>

                <p>Raw material issue has been requested for the following Manufacturing Order:</p>

                <p>
                    <b>MO:</b> {mo.name}<br/>
                    <b>Product:</b> {mo.product_id.display_name}<br/>
                    <b>Quantity:</b> {mo.product_qty}
                </p>

                <p>Please issue the required raw materials.</p>
            """

            mail_values = {
                'subject': f'RM Issue Request for {mo.name}',
                'body_html': body,
                'email_to': 'store@rsdpolymers.com',
                'email_from': 'production@rsdpolymers.com',
            }

            self.env['mail.mail'].sudo().create(mail_values).send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'RM Issue Request sent to Store Department.',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }

    # -----------------------------------------------------
    # RM ISSUE DONE (Store → Production)
    # -----------------------------------------------------

    def action_rm_issue(self):

        for mo in self:

            if mo.is_packing_order:
                continue

            if mo.rm_issue_status != 'requested':
                raise UserError("RM issue request not found.")

            mo.rm_issue_status = 'issued'

            body = f"""
                <p>Hello Production Team,</p>

                <p>Raw materials have been issued for the following Manufacturing Order:</p>

                <p>
                    <b>MO:</b> {mo.name}<br/>
                    <b>Product:</b> {mo.product_id.display_name}<br/>
                    <b>Quantity:</b> {mo.product_qty}
                </p>

                <p>You may now start production.</p>
            """

            mail_values = {
                'subject': f'Raw Material Issued for {mo.name}',
                'body_html': body,
                'email_to': 'production@rsdpolymers.com',
                'email_from': 'store@rsdpolymers.com',
            }

            self.env['mail.mail'].sudo().create(mail_values).send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Raw Materials issued successfully. Production team notified.',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }