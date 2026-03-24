from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class RmIssue(models.Model):
    _name = 'rm.issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'RM Issue'
    _rec_name = 'name'

    name = fields.Char(default='New', readonly=True, copy=False)

    mo_id = fields.Many2one('mrp.production', required=True, string="Manufacturing Order")
    sale_id = fields.Many2one('sale.order', string="Sales Order")

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('issued', 'Issued')
    ], default='draft', tracking=True)

    line_ids = fields.One2many('rm.issue.line', 'rm_issue_id')

    requested_by = fields.Many2one('res.users')
    issued_by = fields.Many2one('res.users')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rm.issue') or 'New'
        return super().create(vals_list)

    def action_mark_requested(self):
        self.state = 'requested'
        self.requested_by = self.env.user

    def action_issue_material(self):

        for rm in self:

            if rm.state != 'requested':
                raise UserError("RM issue request not found.")

            self.state = 'issued'
            self.issued_by = self.env.user
            self.mo_id.rm_issue_status = 'issued'

            body = f"""
                <p>Hello Production Team,</p>

                <p>Raw materials have been issued for the following Manufacturing Order:</p>

                <p>
                    <b>MO:</b> {self.mo_id.name}<br/>
                    <b>Product:</b> {self.mo_id.product_id.display_name}<br/>
                    <b>Quantity:</b> {self.mo_id.product_qty}
                </p>

                <p>You may now start production.</p>
            """

            mail_values = {
                'subject': f'Raw Material Issued for {self.mo_id.name}',
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

    def action_print_rm_slip(self):
        self.ensure_one()

        # Ensure there is an MO linked before trying to print
        if not self.mo_id:
            raise UserError("There is no Manufacturing Order linked to this RM Issue to print.")

        # Call the existing report, passing the linked mo_id as the target record
        # Note: Replace 'your_module_name' with the actual technical name of the
        # module where the report XML is located (likely 'rm_issue_slip' based on your code).
        return self.env.ref('rsd_production.action_rm_issue_slip').report_action(self.mo_id)