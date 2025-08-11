from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class TallyLedgerGroup(models.Model):
    _name = 'tally.ledger.group'
    _description = 'Tally Ledger Group'
    _order = 'name'  # Order records by name by default
    _rec_name = 'name'  # Use 'name' field as the display name for records

    name = fields.Char(
        string="Tally Group Name",
        required=True,
        help="The exact name of the Ledger Group as it appears in TallyPrime/Tally.ERP 9."
    )

    parent_id = fields.Many2one(
        'tally.ledger.group',
        string="Parent Group",
        index=True,
        ondelete='restrict',  # Prevent deletion if child groups exist
        help="The parent group in Tally's hierarchy. Leave empty for primary groups."
    )

    child_ids = fields.One2many(
        'tally.ledger.group',
        'parent_id',
        string="Child Groups"
    )

    is_primary_group = fields.Boolean(
        string="Is Primary Group?",
        help="Indicates if this is one of Tally's predefined top-level primary groups (e.g., Capital Account, Sales Accounts)."
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

    description = fields.Text(
        string="Description",
        help="Any additional notes or description for this Tally Ledger Group."
    )

    # SQL constraints for data integrity
    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'The Tally Group name must be unique!'),
    ]

    def create(self, vals):
        _logger.info(f"Creating new Tally Ledger Group: {vals.get('name')}")
        return super(TallyLedgerGroup, self).create(vals)

    def write(self, vals):
        _logger.info(f"Updating Tally Ledger Group {self.name}: {vals}")
        return super(TallyLedgerGroup, self).write(vals)

    def unlink(self):
        # You might add a check here to prevent deleting groups that are actively linked to accounts
        for group in self:
            if self.env['account.account'].search_count([('tally_group_id', '=', group.id)]):
                raise ValidationError(
                    _("Cannot delete Tally Ledger Group '%s' as it is linked to one or more accounts.") % group.name)
        return super(TallyLedgerGroup, self).unlink()

    @api.model
    def import_tally_ledger_groups_action(self):
        """
        Action to trigger the import of Tally Ledger Groups from TallyPrime.
        This method will be called by a button in the UI.
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': "Import Groups from Tally button clicked! Implement your import logic here.",
                'type': 'success',
                'sticky': False,
            }
        }