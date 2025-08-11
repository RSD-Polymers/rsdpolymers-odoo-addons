from odoo import fields, models

class AccountAccount(models.Model):
    _inherit = 'account.account'

    is_posted_to_tally = fields.Boolean(
        string="Posted to Tally",
        default=False,
        help="Indicates if this Chart of Account has been successfully posted to Tally."
    )

    tally_group_id = fields.Many2one(
        'tally.ledger.group',
        string="Tally Group",
        help="The corresponding Tally Ledger Group for this Odoo account."
    )

    tally_guid = fields.Char(
        string="Tally GUID",
        copy=False,  # GUID should not be copied when duplicating records
        help="The Global Unique Identifier for this group as provided by Tally (if available)."
    )

    last_sync_date = fields.Datetime(
        string="Last Synced On",
        readonly=True,  # Should be updated by sync process, not manually
        help="Date and time when this group was last synchronized from Tally."
    )

    tally_opening_balance_amount = fields.Float(string="Tally Opening Balance Amount",
                                                  help="Opening balance amount fetched from Tally Prime. This is a staging field for creating Odoo journal entries.")
    tally_opening_balance_is_debit = fields.Boolean(string="Tally Opening Balance is Debit",
                                                      help="True if the Tally opening balance is a Debit, False if Credit. Used for staging.")
    tally_opening_balance_imported = fields.Boolean(string="Opening Balance Journal Entry Created", default=False,
                                                      help="Indicates if the Tally opening balance has been successfully processed into an Odoo journal entry.")
