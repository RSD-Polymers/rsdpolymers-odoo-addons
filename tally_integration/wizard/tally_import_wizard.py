from datetime import datetime
import re
from importlib.resources._common import _

#from importlib.resources import _

import pyodbc
import requests
from lxml import etree
from odoo import models, fields
import logging
import html

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# Add a helper for GST treatment mapping
def _map_tally_gst_treatment(tally_gst_type):
    """
    Maps Tally's GST Registration Type string to Odoo's l10n_in_gst_treatment selection key.
    Returns None if the Tally type is empty/null or no direct mapping is found.
    """
    if not tally_gst_type:
        return None  # Explicitly return None for null/empty from Tally

    tally_gst_type_lower = tally_gst_type.lower().strip()

    # Mapping Tally's GST Registration Type to Odoo's l10n_in_gst_treatment selection values
    # These keys (regular, composition, etc.) must match the first element of the tuples
    # in the l10n_in_gst_treatment fields.Selection definition you provided.
    mapping = {
        'regular': 'regular',
        'composition': 'composition',
        'unregistered': 'unregistered',
        'consumer': 'consumer',
        'overseas': 'overseas',
        'foreign': 'overseas',  # Common Tally term for Overseas
        'special economic zone': 'special_economic_zone',  # Tally uses 'Special Economic Zone'
        'sez': 'special_economic_zone',  # Common Tally abbreviation
        'deemed export': 'deemed_export',
        'uin holders': 'uin_holders',  # Tally uses 'UIN Holders'
    }

    # Return mapped value or None if no direct match.
    return mapping.get(tally_gst_type_lower)

def _clean_invalid_xml_chars(text):
    """
    Remove characters that are not allowed in XML 1.0,
    including encoded references like &#4; which lxml will reject.
    """
    # Remove direct illegal characters
    text = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]', '', text)

    # Remove numeric character references like &#0; to &#8; etc. (except tab/newline/carriage return)
    text = re.sub(
        r'&#(0?[0-8]|0?11|0?12|0?14|0?15|0?16|0?17|0?18|0?19|0?20|0?21|0?22|0?23|0?24|0?25|0?26|0?27|0?28|0?29|0?30|0?31);',
        '', text)

    return text


TALLY_GROUP_TO_ODOO_ACCOUNT_TYPE_MAP = {
    'capital account': 'equity',
    'loans (liability)': 'liability_non_current',
    'current liabilities': 'liability_current',
    'fixed assets': 'asset_fixed',
    'current assets': 'asset_current',
    'investments': 'asset_non_current',
    'sales accounts': 'income',
    'purchase accounts': 'expense_direct_cost',
    'direct expenses': 'expense_direct_cost',
    'indirect expenses': 'expense',
    'direct incomes': 'income',
    'indirect incomes': 'income_other',
    'bank accounts': 'asset_cash',
    'cash-in-hand': 'asset_cash',
    'duties & taxes': 'liability_current',
    'suspense a/c': 'off_balance',
    'branch / divisions': 'asset_current',
    'stock in hand': 'asset_current',
    'deposits (asset)': 'asset_current',
    'reserves & surplus': 'equity',
    'secured loans': 'liability_non_current',
    'unsecured loans': 'liability_non_current',
    'sundry creditors': 'liability_payable',
    'provisions': 'liability_current',
    'miscellaneous expenses (asset)': 'asset_current',
    'sundry debtors': 'asset_receivable',
    'capital work in progress': 'asset_fixed',
    'sundry creditors for expenses': 'liability_payable',
    'sundry creditors for capex': 'liability_payable',
    'sundry creditors for rm': 'liability_payable',
    'loans & advances (asset)': 'asset_receivable',
    'direct taxes paid': 'expense',              # Corrected from 'expense_other'
    'advertisement & donations': 'expense',      # Corrected from 'expense_marketing'
    'employee cost-apprentice': 'expense',       # CORRECTED from 'expense_payroll'
    'mobile phone': 'expense',
    'finance cost': 'expense_depreciation',      # Valid
    'bank charges': 'expense',                   # CORRECTED from 'expense_bank'
    'computer & softwares': 'expense_direct_cost',
    'legal & professional charges': 'expense',   # CORRECTED from 'expense_professional_services'
    'excise duty': 'liability_current',
    'employee cost - factory': 'expense',        # CORRECTED from 'expense_payroll'
    'input gst maharashtra': 'asset_current',
    'maharashtra vat': 'liability_current',
    'employee cost - office': 'expense',
    'fcm': 'liability_current',
    'plant & machinery': 'asset_fixed',
    'amar enterprises': 'asset_receivable',
    'advance to staff': 'asset_receivable',
    'loan from directors': 'liability_non_current',
    'books & periodicals': 'expense',
    'building & construction': 'asset_fixed',
    'miscelleneous charges': 'expense',
    'motor vehicles': 'asset_fixed',
    'electrical installation': 'asset_fixed',
    'bank od a/c': 'liability_current',
    'interest on statutory payments': 'expense',
    'directors remuneration': 'expense',
    'local sales': 'income',
    'goods and service tax': 'liability_current',
    'electronic cash ledger': 'liability_current',
    'electronic credit ledger': 'asset_current',
    'lc deposit': 'asset_non_current',
    'fd for cng': 'asset_non_current',
    'mpcb deposit': 'asset_non_current',
    'fix deposit': 'asset_non_current',
    'service item': 'expense',
    'export sales': 'income',
    'sales': 'income',
    'furniture & fixtures': 'asset_fixed',
    'rcm itc': 'asset_current',
    'gst - purchase': 'asset_current',
    'stock-in-hand': 'asset_current',
    'suspense': 'off_balance',
    'leasehold land': 'asset_fixed',
    'office equipments': 'asset_fixed',
    'consumable': 'expense',
    'prelimnary expenses': 'asset_non_current',
    'primary': 'equity',
    'rent expenses': 'expense',
    'share application money': 'liability_current',
    'tax deducted at source(tds)': 'liability_current',
    'printing & stationary expenses': 'expense',
    'factory building': 'asset_fixed',
    'insurance charges': 'expense',
    'output gst maharshtra': 'liability_current',
}

ODOO_ACCOUNT_TYPE_TO_SEQUENCE_CODE_MAP = {
    'asset_fixed': 'account.code.asset.fixed',
    'asset_current': 'account.code.asset.current',
    'asset_non_current': 'account.code.asset.non_current',
    'asset_cash': 'account.code.asset.cash',
    'asset_receivable': 'account.code.asset.receivable',
    'liability_current': 'account.code.liability.current',
    'liability_payable': 'account.code.liability.payable',
    'liability_non_current': 'account.code.liability.non_current',
    'equity': 'account.code.equity',
    'income': 'account.code.income',
    'income_other': 'account.code.income.other',
    'expense': 'account.code.expense',
    'expense_direct_cost': 'account.code.expense.direct.cost',
    'expense_depreciation': 'account.code.expense.depreciation',
    'off_balance': 'account.code.off.balance',
}

def _get_odoo_account_type(tally_parent_group_name):
    """
    Maps a Tally parent group name to an Odoo account.account selection key.
    """
    _logger.info(f"Tally Parent coming as : '{tally_parent_group_name}'.")

    odoo_account_type_key = TALLY_GROUP_TO_ODOO_ACCOUNT_TYPE_MAP.get(
        tally_parent_group_name.lower().strip()
    )
    if odoo_account_type_key:
        return odoo_account_type_key
    _logger.warning(
        f"No direct Odoo Account Type selection key mapping found for Tally group '{tally_parent_group_name}'. "
        "Consider adding it to TALLY_GROUP_TO_ODOO_ACCOUNT_TYPE_MAP."
    )
    return False


class TallyImportWizard(models.TransientModel):
    _name = 'tally.import.wizard'
    _description = 'Import Data from Tally Wizard'

    # A simple field to display a message on the wizard form
    message_field = fields.Char(string="Information",
                                default="This is a Wizard to Import Tally Groups, Ledgers, Cost Centers etc into Odoo. Click a button to initiate Tally import process.",
                                readonly=True)
    xml_file = fields.Binary(string="Upload Tally XML File", required=True,
                             help="Upload the XML file exported from Tally Prime (e.g., All Masters.xml)")
    xml_file_name = fields.Char(string="XML File Name")

    def _get_tally_connection_details(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        tally_company_name = ICPSudo.get_param('odoo_tally_integration.tally_company_name')
        tally_host = ICPSudo.get_param('odoo_tally_integration.tally_host')
        tally_port = ICPSudo.get_param('odoo_tally_integration.tally_port')
        tally_xml_path = ICPSudo.get_param('odoo_tally_integration.tally_xml_path')

        if not all([tally_company_name, tally_host, tally_port]):
            raise UserError(
                "Tally integration settings (Company Name, Host, Port) are not configured. Please configure them in Settings > Tally Integration.")
        tally_api_url = f"http://{tally_host}:{tally_port}"

        return tally_company_name, tally_api_url, tally_xml_path

    def _get_tally_company_name_setting(self):
        """Retrieves the configured Tally company name from Odoo settings."""
        ICPSudo = self.env['ir.config_parameter'].sudo()
        tally_company_name_setting = ICPSudo.get_param('odoo_tally_integration.tally_company_name')
        if not tally_company_name_setting:
            raise UserError("Tally Company Name (in Tally) is not configured in Settings > Tally Integration.")
        return tally_company_name_setting

    def _get_tally_odbc_connection_details(self):
        """Retrieves Tally ODBC connection string from Odoo settings."""
        ICPSudo = self.env['ir.config_parameter'].sudo()
        odbc_dsn = ICPSudo.get_param('odoo_tally_integration.tally_odbc_dsn')
        odbc_driver = ICPSudo.get_param('odoo_tally_integration.tally_odbc_driver')
        odbc_port = ICPSudo.get_param('odoo_tally_integration.tally_odbc_port') or '9000'
        tally_odbc_remote_host = ICPSudo.get_param('odoo_tally_integration.tally_odbc_remote_host') or 'localhost'

        if odbc_dsn:
            conn_str = f"DSN={odbc_dsn}"
        elif odbc_driver:
            url = f"http://{tally_odbc_remote_host}:{odbc_port}"
            conn_str = f"DRIVER={odbc_driver};URL={url}"
        else:
            raise UserError(
                "Tally ODBC connection settings (DSN or Driver/Host/Port) are not configured. "
                "Please configure them in Settings > Tally Integration."
            )

        return conn_str

    def action_import_tally_groups(self):
        self.ensure_one()

        tally_company_name, tally_api_url, _ = self._get_tally_connection_details()

        xml_payload = f"""
        <ENVELOPE>
          <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>Export</TALLYREQUEST>
            <TYPE>Collection</TYPE>
            <ID>Group Collection</ID>
          </HEADER>
          <BODY>
            <DESC>
              <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                <SVCURRENTCOMPANY>{tally_company_name}</SVCURRENTCOMPANY>
              </STATICVARIABLES>
              <TDL>
                <TDLMESSAGE>
                  <COLLECTION NAME="Group Collection" ISMODIFY="No">
                    <TYPE>Group</TYPE>
                    <FETCH>NAME, PARENT, GUID, ISBILLWISEON, ISCOSTCENTRESON, AFFECTSGROSSPROFIT</FETCH>
                  </COLLECTION>
                </TDLMESSAGE>
              </TDL>
            </DESC>
          </BODY>
        </ENVELOPE>
        """

        headers = {"Content-Type": "application/xml"}

        try:
            response = requests.post(tally_api_url, data=xml_payload.encode('utf-8'), headers=headers, timeout=15)

            if response.status_code != 200:
                raise UserError(_(f"Tally response failed with status code: {response.status_code}"))

            cleaned_text = _clean_invalid_xml_chars(response.text)
            xml_tree = etree.fromstring(cleaned_text.encode("utf-8"))

            groups = xml_tree.xpath('//GROUP')
            if not groups:
                _logger.warning("No <GROUP> elements found in Tally XML response. Check XML structure or Tally data.")
                # Return notification and close the wizard even if no groups found
                return [{
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Tally Import Warning"),
                        'message': _(
                            "No groups were found in TallyPrime response. Check company name, Tally XML API settings, and Tally data."),
                        'type': 'warning',
                        'sticky': False,
                    }
                }, {
                    'type': 'ir.actions.act_window_close',
                }]

            group_imported_count = 0
            group_data_for_second_pass = {}
            tally_ledger_group_model = self.env['tally.ledger.group']

            for group_element in groups:
                name = group_element.findtext(".//LANGUAGENAME.LIST/NAME.LIST/NAME")
                parent_name = group_element.findtext("PARENT")
                guid = group_element.findtext("GUID")

                if not guid:
                    _logger.warning(f"Skipping group '{name}' due to missing GUID")
                    continue

                is_primary_group = parent_name.strip().lower() in ('primary', 'primary group')

                vals = {
                    'name': name,
                    'tally_guid': guid,
                    'is_primary_group': is_primary_group,
                    'last_sync_date': datetime.now(),
                }

                existing = tally_ledger_group_model.search([('tally_guid', '=', guid)], limit=1)
                if existing:
                    existing.write(vals)
                else:
                    existing = tally_ledger_group_model.create(vals)

                group_data_for_second_pass[guid] = {
                    'odoo_record': existing,
                    'parent_name': parent_name
                }
                group_imported_count += 1

            for guid, data in group_data_for_second_pass.items():
                odoo_group = data['odoo_record']
                parent_name = data['parent_name']
                if parent_name and odoo_group.name != parent_name:
                    parent = tally_ledger_group_model.search([('name', '=', parent_name)], limit=1)
                    if parent and odoo_group.parent_id != parent:
                        odoo_group.write({'parent_id': parent.id})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Tally Data Import Successful",
                    'message': f"Successfully imported/updated {group_imported_count} Tally Groups via HTTP.",
                    'type': 'success',
                    'sticky': False,
                },
                'target': 'main',
                'context': {'reload_menu': True},
            }

        except Exception as e:
            _logger.error("Tally Group Import Failed: %s", str(e), exc_info=True)
            raise UserError(f"Tally Import Failed: {e}")

    def action_import_tally_ledgers(self):
        self.ensure_one()

        tally_company_name, tally_api_url, _ = self._get_tally_connection_details()

        xml_payload = f"""
                <ENVELOPE>
                  <HEADER>
                    <VERSION>1</VERSION>
                    <TALLYREQUEST>Export</TALLYREQUEST>
                    <TYPE>Collection</TYPE>
                    <ID>Ledger Collection</ID>
                  </HEADER>
                  <BODY>
                    <DESC>
                      <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                        <SVCURRENTCOMPANY>{tally_company_name}</SVCURRENTCOMPANY>
                      </STATICVARIABLES>
                      <TDL>
                        <TDLMESSAGE>
                          <COLLECTION NAME="Ledger Collection" ISMODIFY="No">
                            <TYPE>Ledger</TYPE>
                            <FETCH>NAME, GUID, PARENT, ISBILLWISEON, ISCOSTCENTRESON, ISSUBLEDGER, AFFECTSSTOCK, OPENINGBALANCE, ISDEEMEDPOSITIVE</FETCH>
                          </COLLECTION>
                        </TDLMESSAGE>
                      </TDL>
                    </DESC>
                  </BODY>
                </ENVELOPE>
                """

        headers = {"Content-Type": "application/xml"}

        try:
            _logger.info("Sending request to Tally for Ledgers...")
            response = requests.post(tally_api_url, data=xml_payload.encode('utf-8'), headers=headers,
                                     timeout=30)  # Increased timeout

            if response.status_code != 200:
                raise UserError(
                    f"Tally response failed with status code: {response.status_code}. Response: {response.text}")

            cleaned_text = _clean_invalid_xml_chars(response.text)
            xml_tree = etree.fromstring(cleaned_text.encode("utf-8"))

            ledgers = xml_tree.xpath('//LEDGER')
            if not ledgers:
                _logger.warning("No <LEDGER> elements found in Tally XML response. Check XML structure or Tally data.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Tally Import Warning"),
                        'message': _(
                            "No ledgers were found in TallyPrime response. Check company name, Tally XML API settings, and Tally data."),
                        'type': 'warning',
                        'sticky': False,
                    }
                }

            ledger_imported_count = 0
            account_account_model = self.env['account.account']
            tally_ledger_group_model = self.env['tally.ledger.group']

            for ledger_element in ledgers:
                name = ledger_element.findtext(".//LANGUAGENAME.LIST/NAME.LIST/NAME")
                parent_name = ledger_element.findtext("PARENT")
                guid = ledger_element.findtext("GUID")
                is_bill_wise_on = ledger_element.findtext("ISBILLWISEON") == 'Yes'
                is_cost_centres_on = ledger_element.findtext("ISCOSTCENTRESON") == 'Yes'
                opening_balance_str = ledger_element.findtext("OPENINGBALANCE")
                is_deemed_positive = ledger_element.findtext("ISDEEMEDPOSITIVE")  # "Yes" for debit, "No" for credit

                # --- Handle Opening Balance ---
                opening_balance_amount = 0.0
                opening_balance_is_debit = False
                if opening_balance_str:
                    try:
                        # Tally's OPENINGBALANCE can be negative for credit balances
                        # ISDEEMEDPOSITIVE tells us the natural balance type
                        opening_balance_amount = abs(float(opening_balance_str))
                        if is_deemed_positive == 'Yes':  # Natural balance is Debit (e.g., Assets, Expenses)
                            opening_balance_is_debit = (float(opening_balance_str) >= 0)
                        else:  # Natural balance is Credit (e.g., Liabilities, Income, Equity)
                            opening_balance_is_debit = (float(opening_balance_str) < 0)

                    except ValueError:
                        _logger.warning(
                            f"Could not parse OPENINGBALANCE '{opening_balance_str}' for ledger '{name}'. Setting to 0.")
                        opening_balance_amount = 0.0

                if not guid:
                    _logger.warning(f"Skipping ledger '{name}' due to missing GUID")
                    continue
                if not name:
                    _logger.warning(f"Skipping ledger with GUID '{guid}' due to missing Name")
                    continue

                # Find corresponding Tally Ledger Group
                tally_group_record = False
                if parent_name:
                    tally_group_record = tally_ledger_group_model.search([('name', '=', parent_name)], limit=1)
                    if not tally_group_record:
                        _logger.warning(f"Tally Group '{parent_name}' not found in Odoo for ledger '{name}'. "
                                        "Please import Tally Groups first or ensure the group exists.")
                parent_name = html.unescape(parent_name)
                parent_name = parent_name.strip()
                # Determine Odoo Account Type
                odoo_account_type = _get_odoo_account_type(parent_name)
                if not odoo_account_type:
                    _logger.warning(
                        f"Could not determine Odoo Account Type for ledger '{name}' (Tally Parent: '{parent_name}'). Skipping.")
                    continue

                # --- START: Modified Code Generation using ir.sequence ---
                generated_code = False
                sequence_code = ODOO_ACCOUNT_TYPE_TO_SEQUENCE_CODE_MAP.get(odoo_account_type)
                if sequence_code:
                    generated_code = self.env['ir.sequence'].next_by_code(sequence_code)
                    if not generated_code:
                        _logger.error(
                            f"Sequence with code '{sequence_code}' not found or configured for account type '{odoo_account_type}'. Please set it up in Odoo.")
                        # Fallback to a modified name-based code if sequence generation fails
                        raw_code = name.upper()
                        generated_code = re.sub(r'[^A-Z0-9.]', '', raw_code)
                else:
                    _logger.warning(
                        f"No sequence mapping found for Odoo account type '{odoo_account_type}'. Falling back to name-based code for ledger '{name}'.")
                    raw_code = name.upper()
                    generated_code = re.sub(r'[^A-Z0-9.]', '', raw_code)

                code = generated_code
                # --- END: Modified Code Generation using ir.sequence ---

                # Determine the 'reconcile' field value
                # Force reconcile to True for Receivable and Payable types
                should_reconcile = is_bill_wise_on
                if odoo_account_type in ['asset_receivable', 'liability_payable']:
                    should_reconcile = True

                vals = {
                    'name': name,
                    'code': code,  # This will be the dynamically generated code
                    'account_type': odoo_account_type,
                    'reconcile': should_reconcile,  # Odoo's reconcile field
                    'tally_group_id': tally_group_record.id if tally_group_record else False,
                    'last_sync_date': datetime.now(),  # Assuming you add this field to account.account
                    'tally_guid': guid,  # Assuming you add this field to account.account
                    'tally_opening_balance_amount': opening_balance_amount,
                    'tally_opening_balance_is_debit': opening_balance_is_debit,
                    'tally_opening_balance_imported': False,  # Mark as not yet processed for JE
                }

                # Check for existing account by Tally GUID
                existing_account = account_account_model.search([
                    ('name', '=', name),
                    ('tally_guid', '=', guid),
                ], limit=1)

                if existing_account:
                    # Update existing account
                    # Remove 'code' from update if it's not meant to be changed after creation
                    update_vals = vals.copy()
                    if 'code' in update_vals and existing_account.code != update_vals['code']:
                        _logger.warning(f"Code for existing account '{name}' (GUID: {guid}) will not be updated "
                                        f"from '{existing_account.code}' to '{update_vals['code']}'. "
                                        "Odoo account codes are typically stable.")
                        del update_vals['code']  # Prevent changing code on existing accounts
                    # Do not overwrite tally_opening_balance_imported if it's already True (means JE created)
                    if existing_account.tally_opening_balance_imported and 'tally_opening_balance_imported' in update_vals:
                        del update_vals['tally_opening_balance_imported']

                    existing_account.write(update_vals)
                    _logger.info(f"Updated Odoo account '{name}' (GUID: {guid})")
                else:
                    # Create new account
                    # Ensure code uniqueness for new accounts
                    if account_account_model.search([('code', '=', code)],
                                                    limit=1):
                        _logger.warning(
                            f"Account with code '{code}' already exists. Attempting to create with a modified code for '{name}'.")
                        # Simple fallback: append a number if code exists
                        i = 1
                        new_code = f"{code}.{i}"
                        while account_account_model.search(
                                [('code', '=', new_code)], limit=1):
                            i += 1
                            new_code = f"{code}.{i}"
                        vals['code'] = new_code
                        _logger.info(f"New code for '{name}' set to '{new_code}'")

                    account_account_model.create(vals)
                    _logger.info(f"Created Odoo account '{name}' (Code: {vals['code']})")

                ledger_imported_count += 1

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Tally Data Import Successful",
                    'message': f"Successfully imported/updated {ledger_imported_count} Tally Ledgers via HTTP.",
                    'type': 'success',
                    'sticky': False,
                },
                'target': 'main',
                'context': {'reload_menu': True},
            }

        except requests.exceptions.Timeout:
            _logger.error(
                "Tally Ledger Import Failed: Request timed out. Ensure TallyPrime is running and XML API is accessible.")
            raise UserError(
                "Tally Import Failed: Request to TallyPrime timed out. Please check TallyPrime's status and network connectivity.")
        except requests.exceptions.ConnectionError:
            _logger.error("Tally Ledger Import Failed: Could not connect to TallyPrime. Check host and port settings.")
            raise UserError(
                "Tally Import Failed: Could not connect to TallyPrime. Please check Tally host and port in settings.")
        except Exception as e:
            _logger.error("Tally Ledger Import Failed: %s", str(e), exc_info=True)
            raise UserError(f"Tally Import Failed: {e}")

    def action_import_tally_partner_data(self):
        self.ensure_one()

        created_count = 0
        updated_count = 0
        skipped_count = 0
        error_details = []

        res_partner_model = self.env['res.partner']
        country_model = self.env['res.country']
        state_model = self.env['res.country.state']
        tally_group_model = self.env['tally.ledger.group']
        tally_staging_partner = self.env['tally.partner.staging']

        tally_company_name, tally_api_url, _ = self._get_tally_connection_details()
        _logger.info(f"Connecting to Tally Prime API at: {tally_api_url} for company: {tally_company_name}")

        xml_payload = f"""
        <ENVELOPE>
            <HEADER>
                <VERSION>1</VERSION>
                <TALLYREQUEST>Export</TALLYREQUEST>
                <TYPE>Collection</TYPE>
                <ID>Ledger Collection</ID>
            </HEADER>
            <BODY>
                <DESC>
                    <STATICVARIABLES>
                        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
                        <SVCURRENTCOMPANY>{tally_company_name}</SVCURRENTCOMPANY>
                    </STATICVARIABLES>
                    <TDL>
                        <TDLMESSAGE>
                            <COLLECTION NAME="Ledger Collection" ISMODIFY="No">
                                <TYPE>Ledger</TYPE>
                                <FETCH>NAME, GUID, PRIORSTATENAME, GSTREGISTRATIONTYPE, PARENT, COUNTRYOFRESIDENCE, PARTYGSTIN, ISBILLWISEON, ISCOSTCENTRESON, OLDPINCODE</FETCH>
                                <FETCH>CONTACTDETAILS.LIST.PHONENUMBER, CONTACTDETAILS.LIST.MOBILENUMBER</FETCH>
                                <FETCH>LEDMAILINGDETAILS.LIST.ADDRESS.LIST</FETCH>
                                <FETCH>LEDGSTREGDETAILS.LIST</FETCH>
                            </COLLECTION>
                        </TDLMESSAGE>
                    </TDL>
                </DESC>
            </BODY>
        </ENVELOPE>
        """

        headers = {'Content-Type': 'application/xml'}

        try:
            # --- UPDATED REQUEST CALL ---
            response = requests.post(tally_api_url, data=xml_payload.encode('utf-8'), headers=headers, timeout=15)

            # Explicitly check status code before raise_for_status() or parsing
            if response.status_code != 200:
                error_message = _(
                    f"Tally response failed with status code: {response.status_code}. Response: {response.text}")
                _logger.error(error_message)
                raise UserError(error_message)
            # --- END UPDATED REQUEST CALL ---

            # --- UPDATED XML PARSING ---
            cleaned_text = _clean_invalid_xml_chars(response.text)
            xml_tree = etree.fromstring(cleaned_text.encode("utf-8"))  # Using xml_tree as variable name
            # --- END UPDATED XML PARSING ---

            ledgers_data_elements = xml_tree.findall(".//LEDGER")  # Use xml_tree here

            if not ledgers_data_elements:
                _logger.warning(
                    "No ledger data found in Tally XML response. Check your Tally API URL and the XML request.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Tally Customer/Vendor Import Warning"),
                        'message': _(
                            "No customer/vendor ledger data received from Tally. Check API connection and Tally data."),
                        'type': 'warning',
                        'sticky': False,
                    }
                }

            for ledger_elem in ledgers_data_elements:
                try:
                    name = ledger_elem.findtext(".//LANGUAGENAME.LIST/NAME.LIST/NAME")
                    guid = ledger_elem.find('GUID').text if ledger_elem.find('GUID') is not None else ''
                    prior_state_name = ledger_elem.find('PRIORSTATENAME').text if ledger_elem.find(
                        'PRIORSTATENAME') is not None else ''
                    gst_registration_type_tally = ledger_elem.find('GSTREGISTRATIONTYPE').text if ledger_elem.find(
                        'GSTREGISTRATIONTYPE') is not None else ''
                    parent_group = ledger_elem.find('PARENT').text if ledger_elem.find('PARENT') is not None else ''
                    country_of_residence = ledger_elem.find('COUNTRYOFRESIDENCE').text if ledger_elem.find(
                        'COUNTRYOFRESIDENCE') is not None else ''
                    party_gstin = ledger_elem.find('PARTYGSTIN').text if ledger_elem.find(
                        'PARTYGSTIN') is not None else ''
                    pincode = ledger_elem.find('OLDPINCODE').text if ledger_elem.find('OLDPINCODE') is not None else ''

                    ledger_phone = ''
                    ledger_mobile = ''
                    contact_details_list = ledger_elem.find('CONTACTDETAILS.LIST')
                    if contact_details_list is not None:
                        phone_elem = contact_details_list.find('PHONENUMBER')
                        if phone_elem is not None:
                            ledger_phone = phone_elem.text
                        mobile_elem = contact_details_list.find('MOBILENUMBER')
                        if mobile_elem is not None:
                            ledger_mobile = mobile_elem.text

                    address1 = ''
                    address2 = ''
                    mailing_details_list = ledger_elem.find('LEDMAILINGDETAILS.LIST')
                    if mailing_details_list is not None:
                        address_list_elem = mailing_details_list.find('ADDRESS.LIST')
                        if address_list_elem is not None:
                            addr_lines_elements = address_list_elem.findall('ADDRESS')
                            if len(addr_lines_elements) > 0:
                                address1 = addr_lines_elements[0].text if addr_lines_elements[
                                                                              0].text is not None else ''
                            if len(addr_lines_elements) > 1:
                                address2 = addr_lines_elements[1].text if addr_lines_elements[
                                                                              1].text is not None else ''

                    if name:
                        name = name.strip()

                    gstin = party_gstin.strip() if party_gstin else ''

                    pan_no = ''
                    if gstin and len(gstin) == 15 and gstin[2:12].isalnum():
                        pan_no = gstin[2:12].upper()
                    _logger.debug(f"GSTIN: {gstin}, Derived PAN: {pan_no}")

                    gst_treatment_odoo = _map_tally_gst_treatment(gst_registration_type_tally)
                    _logger.debug(
                        f"Tally GST Type: {gst_registration_type_tally}, Mapped Odoo GST Treatment: {gst_treatment_odoo}")

                    parent_group_lower = parent_group.lower().strip() if parent_group else ''
                    is_customer = 'sundry debtors' in parent_group_lower or 'debtors' in parent_group_lower
                    is_vendor = 'sundry creditors' in parent_group_lower or 'creditors' in parent_group_lower

                    if not is_customer and not is_vendor:
                        _logger.info(
                            f"Skipping ledger '{name}' (GUID: {guid}): Not identified as a customer or vendor group (Parent: '{parent_group}').")
                        skipped_count += 1
                        continue

                    street = address1.strip() if address1 else ''
                    street2 = address2.strip() if address2 else ''

                    state_name = prior_state_name.strip() if prior_state_name else ''
                    country_name = country_of_residence.strip() if country_of_residence else ''

                    country_id = country_model.search([('name', '=ilike', country_name)],
                                                      limit=1).id if country_name else False
                    state_id = state_model.search([('name', '=ilike', state_name), ('country_id', '=', country_id)],
                                                  limit=1).id if state_name and country_id else False

                    if state_name and not state_id:
                        _logger.warning(
                            f"State '{state_name}' not found in Odoo for country '{country_name}'. Skipping state for partner '{name}'.")
                    if country_name and not country_id:
                        _logger.warning(
                            f"Country '{country_name}' not found in Odoo. Skipping country for partner '{name}'.")

                    existing_partner = False
                    if gstin:
                        existing_partner = res_partner_model.search([('vat', '=', gstin)], limit=1)

                    if not existing_partner and name:
                        existing_partner = res_partner_model.search([('name', '=ilike', name)], limit=1)
                        if existing_partner and gstin and not existing_partner.vat:
                            existing_partner.write({'vat': gstin})

                    partner_vals = {
                        'name': name,
                        'is_company': True,
                        'customer_rank': 1 if is_customer else 0,
                        'supplier_rank': 1 if is_vendor else 0,
                        'street': street,
                        'street2': street2,
                        'zip': pincode,
                        'city': '',
                        'state_id': state_id,
                        'country_id': country_id,
                        'vat': gstin,
                        'phone': ledger_phone.strip() if ledger_phone else '',
                        'mobile': ledger_mobile.strip() if ledger_mobile else '',
                        'l10n_in_pan': pan_no,
                        'l10n_in_gst_treatment': gst_treatment_odoo,
                    }

                    partner_vals = {k: v for k, v in partner_vals.items() if v is not None and v != ''}

                    if existing_partner:
                        existing_partner.write(partner_vals)
                        updated_count += 1
                        _logger.info(f"Updated existing partner: {name} (ID: {existing_partner.id})")
                    else:
                        res_partner_model.create(partner_vals)
                        created_count += 1
                        _logger.info(f"Created new partner: {name}")

                    existing_tally_group = tally_group_model.search([
                        ('name', '=', parent_group),
                    ], limit=1)

                    staging_vals = {
                        'name': name,
                        'guid': guid,
                        'parent_group_id': existing_tally_group.id if existing_tally_group else False,
                        'gstin': gstin,
                        'pan_no': pan_no,
                        'phone': ledger_phone.strip() if ledger_phone else '',
                        'mobile': ledger_mobile.strip() if ledger_mobile else '',
                        'street': street,
                        'street2': street2,
                        'pincode': pincode,
                        'state_name': state_name,
                        'country_name': country_name,
                        'tally_gst_registration_type': gst_registration_type_tally,
                        'is_customer': is_customer,
                        'is_vendor': is_vendor,
                        'odoo_country_id': country_id,
                        'odoo_state_id': state_id,
                        'odoo_gst_treatment': gst_treatment_odoo,
                    }

                    existing_staging_partner = tally_staging_partner.search([
                        ('guid', '=', guid),
                    ], limit=1)

                    if existing_staging_partner:
                        existing_staging_partner.write(staging_vals)
                    else:
                        tally_staging_partner.create(staging_vals)

                except Exception as e:
                    error_guid = guid if guid else 'N/A'
                    error_name = name if name else 'Unknown'
                    error_msg = f"Error processing Tally ledger '{error_name}' (GUID: {error_guid}): {e}"
                    _logger.error(error_msg, exc_info=True)
                    error_details.append(error_msg)
                    skipped_count += 1

            self.env.cr.commit()

            summary_message = f"Tally Customer/Vendor Import Complete:\nCreated: {created_count}\nUpdated: {updated_count}\nSkipped: {skipped_count}"
            if error_details:
                summary_message += f"\nErrors encountered: {len(error_details)}. See Odoo logs for details."

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Tally Customer/Vendor Import Status",
                    'message': summary_message,
                    'type': "success" if not error_details else "warning",
                    'sticky': True,
                    'next': {
                        'type': 'ir.actions.client',
                        'tag': 'reload',
                    }
                }
            }

        except requests.exceptions.Timeout:
            error_message = _(
                f"Tally Prime API request timed out after 15 seconds. Is Tally running and accessible at {tally_api_url}?")
            _logger.exception(error_message)
            raise UserError(error_message)
        except requests.exceptions.ConnectionError as e:
            error_message = _(
                f"Failed to connect to Tally Prime API at {tally_api_url}. Is Tally running and API enabled? Error: {e}")
            _logger.exception(error_message)
            raise UserError(error_message)
        except requests.exceptions.HTTPError as e:
            # This block might not be strictly necessary with the status_code check above,
            # but it's good for catching other HTTP errors not explicitly handled (e.g., 401, 403, etc.)
            error_message = _(f"Tally Prime API returned an HTTP error ({e.response.status_code}): {e.response.text}")
            _logger.exception(error_message)
            raise UserError(error_message)
        except etree.XMLSyntaxError as e:
            error_message = _(
                f"Failed to parse XML response from Tally Prime. Malformed XML? This might be due to invalid characters in Tally data. Error: {e}")
            _logger.exception(error_message)
            raise UserError(error_message)
        except Exception as e:
            error_message = _(f"An unexpected error occurred during Tally XML import: {e}")
            _logger.exception(error_message)
            raise UserError(error_message)

    def action_create_opening_balance_journal_entries(self):
        self.ensure_one()

        # Define the date for the opening balance journal entry
        # This should be the start date of your fiscal year in Odoo
        # You might want to make this configurable in your wizard or settings
        opening_balance_date = fields.Date.today().replace(month=4, day=1)  # Example: April 1st of current year

        # 1. Create or find the 'Opening Balance' sequence first
        opening_sequence = self.env['ir.sequence'].search([('code', '=', 'account.opening.balance')], limit=1)
        if not opening_sequence:
            opening_sequence = self.env['ir.sequence'].create({
                'name': 'Opening Balance Sequence',
                'code': 'account.opening.balance',
                'prefix': 'OB/',
                'padding': 4,
            })
            _logger.info("Created new 'Opening Balance Sequence'.")

        # Find or create the 'Opening Balance' journal
        # You might want to make the journal configurable
        opening_journal = self.env['account.journal'].search([('code', '=', 'OPENING')], limit=1)
        if not opening_journal:
            opening_journal = self.env['account.journal'].create({
                'name': 'Opening Balance',
                'code': 'OPENING',
                'type': 'general',
                # Do NOT pass 'sequence_id' directly here during journal creation
            })
            _logger.info("Created new 'Opening Balance' journal with default sequence.")

        # Find or create the 'Opening Balance Equity' or 'Suspense' account for balancing
        # This account is crucial for ensuring the journal entry is balanced.
        # It represents the net worth at the start of the period.
        # You should configure this in your Odoo settings or a dedicated field in your module.
        # For demonstration, let's assume an account with code '999999' or similar.
        # It should be of type 'equity' or 'current_assets'/'current_liabilities' (for suspense)
        # It should NOT be reconcilable.
        balancing_account = self.env['account.account'].search([('code', '=', '999999')],
                                                               limit=1)  # Replace with your actual balancing account code
        if not balancing_account:
            # Fallback: create a simple equity account if not found (for dev/testing)
            balancing_account = self.env['account.account'].create({
                'name': 'Opening Balance Equity',
                'code': '999999',
                'account_type': 'equity',
                'reconcile': False,
            })
            _logger.warning(
                "Created a dummy 'Opening Balance Equity' account. Please configure a proper balancing account.")

        # Fetch ledgers that have an opening balance from Tally and haven't been processed yet
        accounts_to_process = self.env['account.account'].search([
            ('tally_opening_balance_amount', '!=', 0.0),
            ('tally_opening_balance_imported', '=', False)
        ])

        if not accounts_to_process:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Opening Balances to Process"),
                    'message': _("No Tally ledgers with unprocessed opening balances found."),
                    'type': 'info',
                    'sticky': False,
                }
            }

        journal_lines = []
        total_debit = 0.0
        total_credit = 0.0

        for account in accounts_to_process:
            amount = account.tally_opening_balance_amount
            is_debit = account.tally_opening_balance_is_debit

            debit_amount = amount if is_debit else 0.0
            credit_amount = amount if not is_debit else 0.0

            # For Sundry Debtors/Creditors, you might need to link to a partner.
            # However, the `OPENINGBALANCE` from Tally's Ledger collection is aggregated.
            # For true bill-wise opening balances, you'd need to fetch individual outstanding bills/invoices from Tally.
            # If you only have the aggregated balance, it will appear as a single unreconciled entry for the account.
            partner_id = False
            if account.account_type in ['asset_receivable', 'liability_payable']:
                # This is a simplification: Odoo usually requires a partner for AR/AP entries.
                # If you have partner GUIDs from Tally, you'd search for them here.
                # Otherwise, you might need a generic "Tally Opening Balance Partner" or
                # accept that these will be unreconciled against a generic partner.
                # For a full migration, you'd import outstanding invoices/bills as actual Odoo invoices/bills.
                _logger.warning(
                    f"Aggregated opening balance for reconcilable account '{account.name}' (Type: {account.account_type}). "
                    "Consider importing individual outstanding invoices/bills for proper reconciliation.")
                # You might try to find a partner based on the ledger name if it matches a contact
                # partner = self.env['res.partner'].search([('name', '=', account.name)], limit=1)
                # if partner:
                #     partner_id = partner.id

            journal_lines.append((0, 0, {
                'account_id': account.id,
                'name': f"Opening Balance from Tally - {account.name}",
                'debit': debit_amount,
                'credit': credit_amount,
                'partner_id': partner_id,  # Link partner if available and appropriate
            }))
            total_debit += debit_amount
            total_credit += credit_amount

        # Create the balancing line
        balancing_debit = 0.0
        balancing_credit = 0.0

        if total_debit > total_credit:
            balancing_credit = total_debit - total_credit
        elif total_credit > total_debit:
            balancing_debit = total_credit - total_debit

        if balancing_debit > 0 or balancing_credit > 0:
            journal_lines.append((0, 0, {
                'account_id': balancing_account.id,
                'name': "Opening Balance Adjustment",
                'debit': balancing_debit,
                'credit': balancing_credit,
            }))
        else:
            _logger.info("Opening balances were perfectly balanced, no balancing entry needed.")

        # Create the main journal entry
        if journal_lines:
            try:
                move = self.env['account.move'].create({
                    'journal_id': opening_journal.id,
                    'date': opening_balance_date,
                    'ref': f"Tally Prime Opening Balances as of {opening_balance_date.strftime('%Y-%m-%d')}",
                    'move_type': 'entry',  # Standard journal entry
                    'line_ids': journal_lines,
                })
                move.action_post()  # Post the journal entry

                # Mark processed accounts as imported
                accounts_to_process.write({'tally_opening_balance_imported': True})

                _logger.info(f"Successfully created and posted opening balance journal entry: {move.name}")

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': "Opening Balances Processed",
                        'message': f"Successfully created and posted opening balance journal entry '{move.name}' for {len(accounts_to_process)} ledgers.",
                        'type': 'success',
                        'sticky': False,
                    },
                    'target': 'main',
                }

            except Exception as e:
                self.env.cr.rollback()  # Rollback transaction if error occurs during JE creation
                _logger.error("Error creating opening balance journal entry: %s", str(e), exc_info=True)
                raise UserError(f"Failed to create opening balance journal entry: {e}")
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Opening Balances to Process"),
                    'message': _("No Tally ledgers with unprocessed opening balances found after initial check."),
                    'type': 'info',
                    'sticky': False,
                }
            }