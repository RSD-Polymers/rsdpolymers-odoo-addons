from odoo import fields, models, api, _
import logging

_logger = logging.getLogger(__name__)


class TallyPartnerLog(models.Model):
    _name = 'tally.partner.staging'
    _description = 'Tally Staging Partner'
    _order = 'create_date desc'

    # Fields to store raw/processed data from Tally ledger
    name = fields.Char(string='Tally Name', required=True, index=True)
    guid = fields.Char(string='Tally GUID', index=True, copy=False, help="Unique identifier from Tally Ledger")
    parent_group_id = fields.Many2one('tally.ledger.group', string='Parent Group', ondelete='set null',
                                      help="Linked Tally parent group from Odoo's tally.ledger.group model.")
    gstin = fields.Char(string='GSTIN', help="GST Identification Number from Tally")
    pan_no = fields.Char(string='PAN', help="Permanent Account Number derived from GSTIN or provided")
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')

    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street2')
    pincode = fields.Char(string='PIN Code')
    city = fields.Char(string='City', help="City information if available from Tally (optional)")
    state_name = fields.Char(string='State Name (Tally)')
    country_name = fields.Char(string='Country Name (Tally)')

    tally_gst_registration_type = fields.Char(string='Tally GST Type', help="Raw GST Registration Type from Tally")
    is_customer = fields.Boolean(string='Customer', default=False)
    is_vendor = fields.Boolean(string='Vendor', default=False)

    # Fields to store processed Odoo-compatible data
    odoo_country_id = fields.Many2one('res.country', string='Odoo Country')
    odoo_state_id = fields.Many2one('res.country.state', string='Odoo State')
    odoo_gst_treatment = fields.Selection([
        ('regular', 'Registered Business - Regular'),
        ('composition', 'Registered Business - Composition'),
        ('unregistered', 'Unregistered Business'),
        ('consumer', 'Consumer'),
        ('overseas', 'Overseas'),
        ('special_economic_zone', 'Special Economic Zone'),
        ('deemed_export', 'Deemed Export'),
        ('uin_holders', 'UIN Holders'),
    ], string="GST Treatment (Odoo)")

    # New computed field
    partner_type_display = fields.Char(string="Partner Type", compute='_compute_partner_type_display', store=True)

    @api.depends('is_customer', 'is_vendor')
    def _compute_partner_type_display(self):
        for record in self:
            if record.is_customer and not record.is_vendor:
                record.partner_type_display = "Customer"
            elif record.is_vendor and not record.is_customer:
                record.partner_type_display = "Vendor"
            else:  # Both false, or (if you allow it) both true
                record.partner_type_display = "None / Both"  # Adjust as needed