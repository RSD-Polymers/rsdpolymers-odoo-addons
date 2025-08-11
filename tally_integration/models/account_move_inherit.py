import uuid

from odoo import fields, models, _, api
from odoo.exceptions import UserError, ValidationError
import requests, logging
import xml.etree.ElementTree as ET
from odoo import _, exceptions
from odoo.api import Environment

_logger = logging.getLogger(__name__)  # Initialize logger


class AccountMove(models.Model):
    _inherit = 'account.move'

    posted_to_tally = fields.Boolean(
        string="Pushed to Tally",
        copy=False,
        default=False,
        readonly=True,
        help="Indicates if this accounting entry has been successfully pushed to Tally."
    )
    tally_response = fields.Text(
        string="Tally Response",
        copy=False,
        help="Response received from Tally after pushing the entry."
    )

    # Computed fields for button visibility
    show_push_to_tally_button = fields.Boolean(
        string="Show Push Button",
        compute='_compute_tally_button_visibility',
        store=False,  # No need to store in DB
    )

    tally_guid = fields.Char(string="Tally GUID", copy=False, readonly=True, index=True,
                             help="Unique Identifier for the voucher in TallyPrime for import/alteration purposes.")

    @api.depends('state', 'posted_to_tally')
    def _compute_tally_button_visibility(self):
        for move in self:
            move.show_push_to_tally_button = move.state == 'posted' and not move.posted_to_tally

    def _get_tally_connection_details(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        tally_company_name = ICPSudo.get_param('odoo_tally_integration.tally_company_name')
        tally_host = ICPSudo.get_param('odoo_tally_integration.tally_host')
        tally_port = ICPSudo.get_param('odoo_tally_integration.tally_port')
        tally_xml_path = ICPSudo.get_param('odoo_tally_integration.tally_xml_path')

        if not all([tally_company_name, tally_host, tally_port]):
            raise UserError(
                _("Tally integration settings (Company Name, Host, Port) are not configured. Please configure them in Settings > Tally Integration."))

        return tally_company_name, tally_host, tally_port, tally_xml_path

    def _generate_tally_xml(self, move, tally_action, voucher_guid):

        invoice = move
        if not invoice.exists():
            raise ValidationError('Invoice not found.')

        if not invoice.invoice_date:
            raise ValidationError(f"Invoice {invoice.name} does not have an invoice date.")

        invoice_date_str = invoice.invoice_date.strftime('%Y%m%d')
        party = invoice.partner_id.name
        party.replace('&', '&amp;')
        # Total invoice amount for the customer (debit)
        amount_total = f"{invoice.amount_total:.2f}"

        narration = f'Invoice {invoice.name} from Odoo Testing'
        if narration.find('&') != -1:
            narration = narration.replace('&', '&amp;')
        if narration.find("'") != -1:
            narration = narration.replace("'", '&apos;')
        if narration.find('"') != -1:
            narration = narration.replace('"', '&quot;')
        if narration.find('–') != -1:
            narration = narration.replace('–', '-')

        tally_company_name, _, _, _ = self._get_tally_connection_details()
        print(tally_company_name)
        # --- Start dynamic LEDGERENTRIES.LIST generation ---
        ledger_entries_xml_parts = []

        # 1. Party/Customer Ledger Entry (Debit)
        # This is typically the first entry and represents the total amount receivable from the customer.
        ledger_entries_xml_parts.append(f"""
                <LEDGERENTRIES.LIST>
                    <OLDAUDITENTRYIDS.LIST TYPE="Number">
                        <OLDAUDITENTRYIDS>-1</OLDAUDITENTRYIDS>
                    </OLDAUDITENTRYIDS.LIST>
                    <LEDGERNAME>{party}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                    <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                    <ISLASTDEEMEDPOSITIVE>Yes</ISLASTDEEMEDPOSITIVE>
                    <AMOUNT>-{amount_total}</AMOUNT>
                    <BILLALLOCATIONS.LIST>
                        <NAME>{invoice.name}</NAME>
                        <BILLCREDITPERIOD P="30 Days">30 Days</BILLCREDITPERIOD>
                        <BILLTYPE>New Ref</BILLTYPE>
                        <AMOUNT>-{amount_total}</AMOUNT>
                    </BILLALLOCATIONS.LIST>
                </LEDGERENTRIES.LIST>
                """)

        # 2. Product/Service Ledger Entries (Credit)
        # Group amounts by actual sales/service ledger (e.g., 'Inter State Sale', 'Transportation Charges - (Inter State)')
        # This handles multiple product lines dynamically.
        sales_ledgers_amounts = {}
        for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            ledger_name = line.account_id.name  # Assuming Odoo account name matches Tally ledger name
            # Escape ledger name for XML
            ledger_name = ledger_name.replace('&', '&amp;')
            sales_ledgers_amounts[ledger_name] = sales_ledgers_amounts.get(ledger_name, 0.0) + line.price_subtotal

        for ledger_name, amount in sales_ledgers_amounts.items():
            if amount > 0:  # Only include if there's an actual amount
                ledger_entries_xml_parts.append(f"""
                    <LEDGERENTRIES.LIST>
                        <OLDAUDITENTRYIDS.LIST TYPE="Number">
                            <OLDAUDITENTRYIDS>-1</OLDAUDITENTRYIDS>
                        </OLDAUDITENTRYIDS.LIST>
                        <LEDGERNAME>{ledger_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISLASTDEEMEDPOSITIVE>No</ISLASTDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{amount:.2f}</AMOUNT>
                        <VATEXPAMOUNT>{amount:.2f}</VATEXPAMOUNT>
                    </LEDGERENTRIES.LIST>
                        """)

        # 3. Tax Ledger Entries (Credit)
        # Consolidate tax amounts by tax ledger (e.g., 'Output IGST', 'Output CGST')
        consolidated_taxes = {}
        # Iterate over all account.move.line records, specifically looking for tax lines
        # In Odoo, tax lines have display_type == 'tax' and usually a specific account_id.
        for line in invoice.line_ids.filtered(lambda l: l.display_type == 'tax' and l.account_id):
            tax_ledger_name = "Output IGST Maharashtra"  # Assuming Odoo tax account name matches Tally ledger name
            # Escape tax ledger name for XML
            tax_ledger_name = tax_ledger_name.replace('&', '&amp;')
            consolidated_taxes[tax_ledger_name] = consolidated_taxes.get(tax_ledger_name, 0.0) + abs(line.balance)

        for tax_ledger_name, amount in consolidated_taxes.items():
            if amount > 0:  # Only include if there's an actual tax amount
                ledger_entries_xml_parts.append(f"""
                    <LEDGERENTRIES.LIST>
                        <OLDAUDITENTRYIDS.LIST TYPE="Number">
                            <OLDAUDITENTRYIDS>-1</OLDAUDITENTRYIDS>
                        </OLDAUDITENTRYIDS.LIST>
                        <APPROPRIATEFOR>GST</APPROPRIATEFOR>
                        <GSTAPPROPRIATETO>Goods and Services</GSTAPPROPRIATETO>
                        <LEDGERNAME>{tax_ledger_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{amount:.2f}</AMOUNT>
                        <VATEXPAMOUNT>{amount:.2f}</VATEXPAMOUNT>
                    </LEDGERENTRIES.LIST>
                        """)

        # Join all generated LEDGERENTRIES.LIST parts
        all_ledger_entries_xml = "\n".join(ledger_entries_xml_parts)
        # --- End dynamic LEDGERENTRIES.LIST generation ---

        xml_string = f"""
                <ENVELOPE>
                    <HEADER>
                        <TALLYREQUEST>Import Data</TALLYREQUEST>
                    </HEADER>
                    <BODY>
                        <IMPORTDATA>
                            <REQUESTDESC>
                                <REPORTNAME>Vouchers</REPORTNAME>
                                <STATICVARIABLES>
                                    <SVCURRENTCOMPANY>{tally_company_name}</SVCURRENTCOMPANY>
                                </STATICVARIABLES>
                            </REQUESTDESC>
                            <REQUESTDATA>
                                <TALLYMESSAGE xmlns:UDF="TallyUDF">
                                    <VOUCHER REMOTEID="{voucher_guid}"
                                             VCHKEY="{voucher_guid}"
                                             VCHTYPE="Sales"
                                             ACTION="{tally_action}"
                                             OBJVIEW="Invoice Voucher View">
                                             <OLDAUDITENTRYIDS.LIST TYPE="Number">
                                                <OLDAUDITENTRYIDS>-1</OLDAUDITENTRYIDS>
                                            </OLDAUDITENTRYIDS.LIST>
                                        <DATE>{invoice_date_str}</DATE>
                                        <REFERENCEDATE>{invoice_date_str}</REFERENCEDATE>
                                        <VCHSTATUSDATE>{invoice_date_str}</VCHSTATUSDATE>
                                        <GUID>{voucher_guid}</GUID>
                                        <NARRATION>{narration}</NARRATION>
                                        <VCHSTATUSDATE>{invoice_date_str}</VCHSTATUSDATE>
                                        <ENTEREDBY>{self.env.user.name}</ENTEREDBY>
                                        <PARTYGSTIN>{invoice.partner_id.vat}</PARTYGSTIN>
                                        <OBJECTUPDATEACTION>{tally_action}</OBJECTUPDATEACTION>
                                        <PARTYNAME>{party}</PARTYNAME>
                                        <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
                                        <PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>
                                        <VOUCHERNUMBER>{invoice.name}</VOUCHERNUMBER>
                                        <BASICBUYERNAME>{party}</BASICBUYERNAME>
                                        <REFERENCE>{invoice.name}</REFERENCE>
                                        <PARTYMAILINGNAME>{party}</PARTYMAILINGNAME>
                                        <UPDATEDDATETIME>{invoice.write_date.strftime('%Y%m%d%H%M%S000') if invoice.write_date else invoice_date_str + '000000000'}</UPDATEDDATETIME>
                                        <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
                                        <ISINVOICE>Yes</ISINVOICE>
                                        <EFFECTIVEDATE>{invoice_date_str}</EFFECTIVEDATE>
                                        <ISGSTOVERRIDDEN>No</ISGSTOVERRIDDEN>
                                        <IGNOREGSTVALIDATION>No</IGNOREGSTVALIDATION>
                                        <VCHGSTSTATUSISINCLUDED>Yes</VCHGSTSTATUSISINCLUDED>
                                        <VCHGSTSTATUSISAPPLICABLE>Yes</VCHGSTSTATUSISAPPLICABLE>

                                        {all_ledger_entries_xml} </VOUCHER>
                                </TALLYMESSAGE>
                            </REQUESTDATA>
                        </IMPORTDATA>
                    </BODY>
                </ENVELOPE>
            """
        return xml_string

    def action_push_to_tally(self):
        self.ensure_one()
        move = self

        current_tally_response_text = ""
        error_occurred = False  # Flag to indicate if an error happened
        error_message_for_user = ""  # Message to display to the user

        if move.state != 'posted':
            # This is a pre-check, can still raise UserError directly as it's not a network error
            raise exceptions.UserError(
                _(f"Invoice {move.name}: Only posted accounting entries can be pushed to Tally."))

        tally_action = 'Create'
        voucher_guid = move.tally_guid

        if not voucher_guid:
            voucher_guid = str(str(self.id) + "-" + self.name[:3])
            tally_action = 'Create'
        else:
            tally_action = 'Alter'

        tally_company_name, tally_host, tally_port, tally_xml_path = self._get_tally_connection_details()
        tally_url = f"http://{tally_host}:{tally_port}"
        headers = {'Content-Type': 'application/xml'}

        xml_data = self._generate_tally_xml(move, tally_action, voucher_guid)
        _logger.info("Generated Tally XML for %s (Action: %s, GUID: %s):\n%s", move.name, tally_action, voucher_guid,
                     xml_data)

        try:
            if tally_xml_path:
                file_path = f"{tally_xml_path}/tally_entry_{move.name.replace('/', '_')}.xml"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(xml_data)
                _logger.info("Tally XML saved to: %s", file_path)

            response = requests.post(tally_url, data=xml_data.encode('utf-8'), headers=headers)
            response.raise_for_status()

            tally_response_xml = response.text
            current_tally_response_text = tally_response_xml
            _logger.info("Tally Raw Response for %s: %s", move.name, tally_response_xml)

            root = ET.fromstring(tally_response_xml)

            created_element = root.find(".//CREATED")
            altered_element = root.find(".//ALTERED")
            errors_element = root.find(".//ERRORS")
            line_error_element = root.find(".//LINEERROR")

            is_successful_tally_response = False
            error_details_from_tally = None

            if line_error_element is not None and line_error_element.text:
                error_details_from_tally = line_error_element.text
                is_successful_tally_response = False
            elif errors_element is not None and errors_element.text and int(errors_element.text) > 0:
                error_details_from_tally = f"Tally reported {errors_element.text} errors."
                is_successful_tally_response = False
            elif created_element is not None and created_element.text == '1':
                success_message_from_tally = f"Invoice {move.name} is Successfully Created/Altered in Tally Prime."
                is_successful_tally_response = True
            elif altered_element is not None and altered_element.text == '1':
                success_message_from_tally = f"Invoice {move.name} is Successfully Created/Altered in Tally Prime."
                is_successful_tally_response = True
            else:
                success_message_from_tally = f"Tally response is ambiguous (HTTP 200, but no clear success/error tags). Assuming successful operation. Raw response: {tally_response_xml}"
                _logger.warning(
                    f"Tally response for {move.name} is ambiguous (HTTP 200, but no clear success/error tags). Assuming success for now. Raw response: {tally_response_xml}")
                is_successful_tally_response = True

            if is_successful_tally_response:
                current_tally_response_text = success_message_from_tally
                write_vals = {
                    'posted_to_tally': True,
                    'tally_response': current_tally_response_text
                }
                if tally_action == 'Create':
                    write_vals['tally_guid'] = voucher_guid
                move.write(write_vals)  # Main transaction write

                # Return success notification with reload
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Success",
                        "message": f"Invoice {move.name} successfully pushed to Tally Prime as {tally_action}.",
                        "type": "success",
                        "sticky": False,
                        "next": {
                            "type": "ir.actions.client",
                            "tag": "reload",
                        }
                    }
                }
            else:
                error_msg_display = error_details_from_tally if error_details_from_tally else "Tally response indicates an unknown error."
                error_message_for_user = f"Failed to push Invoice '{move.name}' to Tally. Details: {error_msg_display}."  # Simpler message for user
                _logger.error(
                    f"{error_message_for_user} Raw response: {current_tally_response_text}")  # Full details in log
                error_occurred = True

        except requests.exceptions.HTTPError as err:
            current_tally_response_text = err.response.text if err.response is not None else str(err)
            error_message_for_user = f"Failed to push Invoice '{move.name}' to Tally. HTTP Error: {err.response.status_code}."
            _logger.error(f"{error_message_for_user} Raw response: {current_tally_response_text}")
            error_occurred = True

        except requests.exceptions.ConnectionError:
            current_tally_response_text = "Connection Error: Could not connect to Tally. Check Tally host and port settings, and ensure Tally is running and accessible."
            error_message_for_user = f"Failed to push Invoice '{move.name}' to Tally. Could not connect to Tally."
            _logger.error(error_message_for_user)
            error_occurred = True

        except ET.ParseError as e:
            raw_response_for_log = tally_response_xml if 'tally_response_xml' in locals() else 'No XML received'
            current_tally_response_text = f"XML Parse Error: {e}. Raw received: {raw_response_for_log}"
            error_message_for_user = f"Failed to parse Tally XML response for Invoice '{move.name}'."
            _logger.error(f"{error_message_for_user} Raw response: {current_tally_response_text}")
            error_occurred = True

        except Exception as e:
            current_tally_response_text = f"An unexpected error occurred: {e}"
            error_message_for_user = f"An unexpected error occurred while pushing Invoice '{move.name}' to Tally."
            _logger.exception(f"{error_message_for_user} Details: {e}")
            error_occurred = True

        finally:
            # This finally block will execute even if an error occurred above.
            # It's responsible for persisting the tally_response, whether success or error.
            if error_occurred:
                new_cr = None
                try:
                    # Use a new cursor to commit the tally_response independently
                    new_cr = self.env.registry.cursor()
                    move_sudo = self.with_env(self.env(cr=new_cr)).browse(move.id)
                    move_sudo.tally_response = current_tally_response_text
                    new_cr.commit()
                except Exception as e_inner:
                    _logger.error(f"Failed to save tally_response in separate transaction: {e_inner}")
                    if new_cr:
                        new_cr.rollback()
                finally:
                    if new_cr:
                        new_cr.close()

        if error_occurred:
            # Instead of raising UserError, return a notification with reload
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error",
                    "message": error_message_for_user,  # Show the simplified message to the user
                    "type": "danger",
                    "sticky": True,  # Keep it on screen until user dismisses
                    "next": {
                        "type": "ir.actions.client",
                        "tag": "reload",  # This will refresh the form
                    }
                }
            }
        # This point should not be reached if success or error is handled
        return {}