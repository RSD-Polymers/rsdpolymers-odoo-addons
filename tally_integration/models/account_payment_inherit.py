import logging

import requests

from odoo import models, fields, api
from datetime import datetime
import xml.etree.ElementTree as ET

from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)  # Initialize logger


def _get_tally_success_message(self):
    """Returns a user-friendly success message based on the payment type."""
    self.ensure_one()
    if self.payment_type == 'outbound':
        return "Vendor Payment %s successfully created/updated in Tally." % self.name
    else:
        return "Customer Receipt %s successfully created/updated in Tally." % self.name

class AccountPaymentTallyExport(models.Model):
    _inherit = 'account.payment'

    posted_to_tally = fields.Boolean(
        string="Pushed to Tally",
        copy=False,
        default=False,
        readonly=True,
        help="Indicates if this accounting entry has been successfully pushed to Tally."
    )

    tally_guid = fields.Char(string="Tally GUID", copy=False, readonly=True, index=True,
                             help="Unique Identifier for the voucher in TallyPrime for import/alteration purposes.")

    tally_response = fields.Text(
        string="Tally Response",
        copy=False,
        readonly=True,
        help="Response received from Tally after pushing the entry."
    )

    tally_narration = fields.Text(
        string="Narration",
        copy=False,
        help="Narration for Tally"
    )

    def _get_tally_connection_details(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        tally_company_name = ICPSudo.get_param('odoo_tally_integration.tally_company_name')
        tally_host = ICPSudo.get_param('odoo_tally_integration.tally_host')
        tally_port = ICPSudo.get_param('odoo_tally_integration.tally_port')
        tally_xml_path = ICPSudo.get_param('odoo_tally_integration.tally_xml_path')

        if not all([tally_company_name, tally_host, tally_port]):
            raise UserError("Tally integration settings (Company Name, Host, Port) are not configured. Please configure them in Settings > Tally Integration.")

        return tally_company_name, tally_host, tally_port, tally_xml_path

    def _get_tally_bill_allocations(self):
        self.ensure_one()
        bill_allocations = []

        reconciled_moves = self.reconciled_bill_ids if self.payment_type == 'outbound' else self.reconciled_invoice_ids
        move_count = len(reconciled_moves)

        tally_sign = 1 if self.payment_type == 'outbound' else -1
        total_amount = round(self.amount, 2)

        if move_count <= 1:
            ref_name = self.memo or "Manual Entry"

            bill_allocations.append({
                'ref_name': ref_name,
                'amount': total_amount * tally_sign,
                'bill_type': 'New Ref' if move_count == 0 else 'Agst Ref',
            })

            return bill_allocations

        if self.payment_type == 'outbound':
            lines = self.env['account.move.line'].search([
                ('move_id', 'in', reconciled_moves.ids),  # Must belong to the multiple bills/invoices
                ('account_id.account_type', '=', 'liability_payable'),  # Must be the Payable/Receivable line
            ])

            if lines:
                for move in reconciled_moves:
                    bill_allocations.append({
                        'ref_name': move.ref,
                        'amount': round(move.amount_total * tally_sign, 2),
                        # Using total amount of the bill as a fallback
                        'bill_type': 'Agst Ref',
                    })
                return bill_allocations

        if self.payment_type == 'inbound':
            lines = self.env['account.move.line'].search([
                ('move_id', 'in', reconciled_moves.ids),  # Must belong to the multiple bills/invoices
                ('display_type' == 'product'),  # Must be the Payable/Receivable line
            ])

            if lines:
                for move in reconciled_moves:
                    bill_allocations.append({
                        'ref_name': move.ref,
                        'amount': round(move.amount_total * tally_sign, 2),
                        # Using total amount of the bill as a fallback
                        'bill_type': 'Agst Ref',
                    })
                return bill_allocations

    def _generate_tally_xml(self, payment, tally_action, voucher_guid):
        payment_date_str = payment.date.strftime('%Y%m%d')
        narration = payment.tally_narration
        is_payment = self.payment_type == 'outbound'
        tally_vchtype = "Payment" if is_payment else "Receipt"

        # --- Escape narration for XML ---
        if narration:
            narration = (
                narration.replace("&", "&amp;")
                .replace("'", "&apos;")
                .replace('"', "&quot;")
                .replace("–", "-")
            )

        tally_company_name, _, _, _ = self._get_tally_connection_details()

        # NOTE: Implement a robust function to map Odoo ledgers/partners to Tally names
        bank_ledger_name = self.journal_id.default_account_id.name
        if self.payment_type == 'outbound':
            if not self.partner_id.tally_payable_account_id:
                raise UserError("Tally Payable Account is not mapped for this Vendor.")
            partner_ledger_name = self.partner_id.tally_payable_account_id.name
        else:
            if not self.partner_id.tally_receivable_account_id:
                raise UserError("Tally Receivable Account is not mapped for this Customer.")
            partner_ledger_name = self.partner_id.tally_receivable_account_id.name

        total_amount = round(self.amount, 2)

        # Tally Signage for Ledger Amounts
        # Partner Ledger: Debit for Payment (Yes), Credit for Receipt (No)
        partner_debit_positive = 'Yes' if is_payment else 'No'
        partner_amount_sign = total_amount if is_payment else -total_amount

        # Bank Ledger: Credit for Payment (No), Debit for Receipt (Yes)
        bank_debit_positive = 'No' if is_payment else 'Yes'
        bank_amount_sign = -total_amount if is_payment else total_amount

        # --- 2. Get Bill Allocation Data ---
        allocations = self._get_tally_bill_allocations()

        # Start VOUCHER
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
                <VOUCHER VCHTYPE="{tally_vchtype}" ACTION="Create">
                    <DATE>{payment_date_str}</DATE>
                    <GUID>{voucher_guid}</GUID>
                    <NARRATION>{narration}</NARRATION>
                    <VOUCHERTYPENAME>{tally_vchtype}</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{self.name}</VOUCHERNUMBER>

                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_ledger_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>{partner_debit_positive}</ISDEEMEDPOSITIVE>
                        <AMOUNT>{partner_amount_sign}</AMOUNT>

                        {''.join(
            f'''
                            <BILLALLOCATIONS.LIST>
                                <NAME>{alloc['ref_name']}</NAME>
                                <AMOUNT>{alloc['amount']}</AMOUNT>
                                <BILLTYPE>Agst Ref</BILLTYPE>
                            </BILLALLOCATIONS.LIST>
                            ''' for alloc in allocations
        )}
                        </ALLLEDGERENTRIES.LIST>

                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{bank_ledger_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>{bank_debit_positive}</ISDEEMEDPOSITIVE>
                        <AMOUNT>{bank_amount_sign}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
                </VOUCHER>
                </TALLYMESSAGE>
                                </REQUESTDATA>
                            </IMPORTDATA>
                        </BODY>
                    </ENVELOPE>
                """

        return xml_string


    def _push_to_tally_core(self):
        """
        Core function to push a move to Tally. Returns a tuple (success, message, guid).
        Does NOT perform any database writes.
        """
        self.ensure_one()
        payment = self
        voucher_guid = payment.tally_guid
        tally_action = "Alter"

        if not voucher_guid:
            # We use the final assigned move.name to ensure the GUID is somewhat unique and traceable
            voucher_guid = str(payment.id)
            tally_action = "Create"

        try:
            xml_data = self._generate_tally_xml(
                payment=payment,
                tally_action=tally_action,
                voucher_guid=voucher_guid
            )

            _logger.info(f"Tally XML for entry {payment.name}:\n{xml_data}")

            # Push to Tally
            tally_company_name, tally_host, tally_port, tally_xml_path = self._get_tally_connection_details()
            tally_url = f"http://{tally_host}:{tally_port}"
            headers = {'Content-Type': 'application/xml'}
            response = requests.post(tally_url, data=xml_data.encode("utf-8"), headers=headers, timeout=60)
            tally_response_xml = response.text or ""

            if response.status_code != 200:
                message = f"Tally returned HTTP {response.status_code}: {response.text}"
                return (False, message, None)

            root = ET.fromstring(tally_response_xml)
            created_element = root.find(".//CREATED")
            altered_element = root.find(".//ALTERED")
            errors_element = root.find(".//ERRORS")
            line_error_element = root.find(".//LINEERROR")

            if line_error_element is not None and line_error_element.text:
                message = f"Tally reported a line error: {line_error_element.text}"
                return (False, message, None)
            elif errors_element is not None and int(errors_element.text) > 0:
                message = f"Tally reported {errors_element.text} errors."
                return (False, message, None)
            elif (created_element is not None and created_element.text == '1') or \
                    (altered_element is not None and altered_element.text == '1'):
                success_message = _get_tally_success_message(payment)
                return (True, success_message, voucher_guid)
            else:
                message = f"Tally response is ambiguous. Raw response: {tally_response_xml}"
                return (False, message, None)

        except requests.exceptions.RequestException as e:
            message = f"Network error connecting to Tally: {str(e)}"
            return (False, message, None)
        except ET.ParseError as e:
            message = f"Failed to parse Tally's XML response: {str(e)}"
            return (False, message, None)
        except Exception as e:
            message = f"Odoo Configuration Error : {str(e)}"
            return (False, message, None)

    def action_push_to_tally(self):
        self.ensure_one()
        success, message, new_guid = self._push_to_tally_core()

        write_vals = {
            'tally_response': message,
        }
        if success:
            write_vals['posted_to_tally'] = True
            if new_guid:
                write_vals['tally_guid'] = new_guid

        self.write(write_vals)

        if success:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Success",
                    "message": message,
                    "type": "success",
                    "sticky": False,
                    "next": {
                        "type": "ir.actions.client",
                        "tag": "reload",
                    }
                }
            }
        else:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Tally Push Error",
                    "message": message,
                    "type": "danger",
                    "sticky": True,
                    "next": {
                        "type": "ir.actions.client",
                        "tag": "reload",
                    }
                }
            }