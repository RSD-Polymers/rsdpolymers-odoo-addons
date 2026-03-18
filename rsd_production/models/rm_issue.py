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

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('rm.issue') or 'New'
        return super().create(vals)

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

            # body = f"""
            #     <p>Hello Production Team,</p>
            #
            #     <p>Raw materials have been issued for the following Manufacturing Order:</p>
            #
            #     <p>
            #         <b>MO:</b> {mo.name}<br/>
            #         <b>Product:</b> {mo.product_id.display_name}<br/>
            #         <b>Quantity:</b> {mo.product_qty}
            #     </p>
            #
            #     <p>You may now start production.</p>
            # """
            #
            # mail_values = {
            #     'subject': f'Raw Material Issued for {mo.name}',
            #     'body_html': body,
            #     'email_to': 'production@rsdpolymers.com',
            #     'email_from': 'store@rsdpolymers.com',
            # }
            #
            # self.env['mail.mail'].sudo().create(mail_values).send()

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