import logging
from odoo import api, Command, fields, models, tools


_logger = logging.getLogger(__name__)



class HrEmployee(models.Model):
    _inherit='hr.employee'

    uan = fields.Char('UAN')
    pf_number = fields.Char('PF No.')
    esi_number = fields.Char('ESI No.')
    account_number = fields.Char('Account No.')
    date_of_joining = fields.Date('Joining Date')