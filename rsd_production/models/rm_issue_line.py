from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class RmIssueLine(models.Model):
    _name = 'rm.issue.line'
    _description = 'RM Issue Line'

    rm_issue_id = fields.Many2one('rm.issue', required=True)
    product_id = fields.Many2one('product.product', required=True)
    qty = fields.Float()
    uom_id = fields.Many2one('uom.uom')