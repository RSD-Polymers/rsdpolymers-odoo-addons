import uuid

from odoo import fields, models, _, api
from odoo.exceptions import UserError, ValidationError
import requests, logging
import xml.etree.ElementTree as ET
from odoo import _, exceptions
from odoo.api import Environment

_logger = logging.getLogger(__name__)  # Initialize logger

MESSAGE_MAP = {
    'out_invoice': "Sales Invoice {num} is Successfully Created/Altered in Tally Prime.",
    'in_invoice': "Purchase Invoice {num} is Successfully Created/Altered in Tally Prime.",
    'entry': "Journal Entry {num} is Successfully Created/Altered in Tally Prime.",
}

def _get_tally_success_message(move):

    template = MESSAGE_MAP.get(
        move.move_type,
        "Document {num} is Successfully Created/Altered in Tally Prime."
    )
    return template.format(num=move.name)


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

    tally_guid = fields.Char(string="Tally GUID", copy=False, readonly=True, index=True,
                             help="Unique Identifier for the voucher in TallyPrime for import/alteration purposes.")

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
            raise UserError(
                _("Tally integration settings (Company Name, Host, Port) are not configured. Please configure them in Settings > Tally Integration."))

        return tally_company_name, tally_host, tally_port, tally_xml_path

    def _generate_tally_xml(self, move, tally_action, voucher_guid):
        """Generate Tally XML for Journal Entries and Customer Invoices"""

        if not move.exists():
            raise ValidationError("Move not found.")

        # CRITICAL: move.name must be the final sequence number here.
        if not move.name or move.name == '/':
            raise ValidationError(f"Move name is not yet assigned for entry with ID {move.id}.")

        if not move.date:
            raise ValidationError(f"Move {move.name} does not have a date.")

        move_date_str = move.date.strftime('%Y%m%d')
        narration = move.tally_narration

        # --- Escape narration for XML ---
        if narration:
            narration = (
            narration.replace("&", "&amp;")
                     .replace("'", "&apos;")
                     .replace('"', "&quot;")
                     .replace("–", "-")
        )

        tally_company_name, _, _, _ = self._get_tally_connection_details()

        ledger_entries_xml_parts = []

        # ==============================
        # CASE 1: Journal Entries (Salary JVs)
        # ==============================
        if move.move_type == 'entry' and move.journal_id.name == 'Salaries':

            # Map ledger names for salary merging
            combine_map = {
                'Salary Expense': 'Salary & Bonus Payable',
                'Salary & Bonus Payable': 'Salary & Bonus Payable',
            }

            ledger_totals = {}

            # ----------------------------
            # 1. COLLECT + MERGE LEDGERS
            # ----------------------------
            for line in move.line_ids.filtered(lambda l: l.account_id):
                raw_name = (line.account_id.name or "").strip()
                target_name = combine_map.get(raw_name, raw_name)

                net = (line.credit or 0.0) - (line.debit or 0.0)
                ledger_totals[target_name] = ledger_totals.get(target_name, 0.0) + net

            # ----------------------------
            # 2. BUILD XML (only once)
            # ----------------------------
            for ledger_name, net_amount in ledger_totals.items():
                if abs(net_amount) < 0.005:
                    continue

                ledger_name_escaped = ledger_name.replace("&", "&amp;")
                is_deemed_positive = "Yes" if net_amount < 0 else "No"
                amount_str = f"-{abs(net_amount):.2f}" if net_amount < 0 else f"{abs(net_amount):.2f}"

                ledger_entries_xml_parts.append(f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{ledger_name_escaped}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>{is_deemed_positive}</ISDEEMEDPOSITIVE>
                        <AMOUNT>{amount_str}</AMOUNT>
                    </LEDGERENTRIES.LIST>
                """)

            voucher_type = "Journal"
            party = ""

        # ==============================
        # CASE 2: Customer Invoices (Sales)
        # ==============================
        elif move.move_type == 'out_invoice':
            invoice = move
            if not invoice.invoice_date:
                raise ValidationError(f"Invoice {invoice.name} does not have an invoice date.")

            invoice_date_str = invoice.invoice_date.strftime('%Y%m%d')
            party = invoice.partner_id.name.replace("&", "&amp;").replace("\n", " ").replace("\r", "").strip()
            amount_total = f"{invoice.amount_total:.2f}"

            # 1. Customer Ledger (Debit)
            ledger_entries_xml_parts.append(f"""
                <LEDGERENTRIES.LIST>
                    <LEDGERNAME>{party}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                    <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                    <AMOUNT>-{amount_total}</AMOUNT>
                    <BILLALLOCATIONS.LIST>
                        <NAME>{invoice.name}</NAME>
                        <BILLTYPE>New Ref</BILLTYPE>
                        <AMOUNT>-{amount_total}</AMOUNT>
                    </BILLALLOCATIONS.LIST>
                </LEDGERENTRIES.LIST>
            """)

            # 2. Sales Ledger(s) (Credit)
            sales_ledgers_amounts = {}
            for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                ledger_name = line.account_id.name.replace("&", "&amp;")
                sales_ledgers_amounts[ledger_name] = sales_ledgers_amounts.get(ledger_name, 0.0) + line.price_subtotal

            for ledger_name, amount in sales_ledgers_amounts.items():
                ledger_entries_xml_parts.append(f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{ledger_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <AMOUNT>{amount:.2f}</AMOUNT>
                    </LEDGERENTRIES.LIST>
                """)

            # 3. Tax Ledger(s) (Credit)
            consolidated_taxes = {}
            for line in invoice.line_ids.filtered(lambda l: l.display_type == 'tax' and l.account_id):
                tax_ledger_name = line.account_id.name.replace("&", "&amp;")
                consolidated_taxes[tax_ledger_name] = consolidated_taxes.get(tax_ledger_name, 0.0) + abs(line.balance)

            for tax_ledger_name, amount in consolidated_taxes.items():
                ledger_entries_xml_parts.append(f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{tax_ledger_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <AMOUNT>{amount:.2f}</AMOUNT>
                    </LEDGERENTRIES.LIST>
                """)

            voucher_type = "Sales"

        # ==============================
        # CASE 3: Vendor Bills (Purchase)
        # ==============================
        elif move.move_type == 'in_invoice':
            invoice = move

            if not invoice.invoice_date:
                raise ValidationError(f"Vendor Bill {invoice.name} does not have an invoice date.")

            invoice_date_str = invoice.invoice_date.strftime('%Y%m%d')

            party = (
                invoice.partner_id.name.replace("&", "&amp;")
                .replace("\n", " ").replace("\r", "").strip()
            )

            amount_total = f"{invoice.amount_total:.2f}"

            # ----------------------------------------
            # 1. Vendor Ledger (Credit)
            # ----------------------------------------
            # Vendor is always credited in purchase voucher
            # Get the payable line from journal items
            payable_line = next(
                (line for line in invoice.line_ids if line.account_id.account_type == 'liability_payable'), None
            )

            vendor_ledger_name = payable_line.account_id.name

            ledger_entries_xml_parts.append(f"""
                       <ALLLEDGERENTRIES.LIST>
                           <LEDGERNAME>{payable_line.account_id.name}</LEDGERNAME>
                           <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                           <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                           <AMOUNT>{payable_line.credit}</AMOUNT>
                           <BILLALLOCATIONS.LIST>
                               <NAME>{invoice.name}</NAME>
                               <BILLTYPE>New Ref</BILLTYPE>
                               <AMOUNT>{payable_line.credit}</AMOUNT>
                           </BILLALLOCATIONS.LIST>
                       </ALLLEDGERENTRIES.LIST>
                   """)

            # ----------------------------------------
            # 2. Purchase Ledger(s) (Debit)
            # ----------------------------------------
            purchase_ledgers_amounts = {}

            for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                ledger_name = line.account_id.name.replace("&", "&amp;")
                purchase_ledgers_amounts[ledger_name] = (
                        purchase_ledgers_amounts.get(ledger_name, 0.0) + line.price_subtotal
                )

            for ledger_name, amount in purchase_ledgers_amounts.items():
                ledger_entries_xml_parts.append(f"""
                           <ALLLEDGERENTRIES.LIST>
                               <LEDGERNAME>{ledger_name}</LEDGERNAME>
                               <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                               <ISPARTYLEDGER>No</ISPARTYLEDGER>
                               <AMOUNT>-{amount:.2f}</AMOUNT>
                           </ALLLEDGERENTRIES.LIST>
                       """)

            # ----------------------------------------
            # 3. Tax Ledger(s) (Debit)
            # ----------------------------------------
            consolidated_taxes = {}

            for line in invoice.line_ids.filtered(lambda l: l.display_type == 'tax' and l.account_id):
                ledger_name = line.account_id.name.replace("&", "&amp;")
                consolidated_taxes[ledger_name] = (
                        consolidated_taxes.get(ledger_name, 0.0) + abs(line.balance)
                )

            for ledger_name, amount in consolidated_taxes.items():
                ledger_entries_xml_parts.append(f"""
                           <ALLLEDGERENTRIES.LIST>
                               <LEDGERNAME>{ledger_name}</LEDGERNAME>
                               <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                               <ISPARTYLEDGER>No</ISPARTYLEDGER>
                               <AMOUNT>-{amount:.2f}</AMOUNT>
                           </ALLLEDGERENTRIES.LIST>
                       """)

            voucher_type = "Purchase"
            party = vendor_ledger_name

        # ==============================
        # CASE 4: Manual JVs
        # ==============================
        elif move.move_type == 'entry' and move.journal_id.type == 'general':
            entry = move

            for line in entry.line_ids:
                if line.debit > 0:
                    amount = line.debit
                    tally_amount = f"-{amount}"
                    is_deemed_positive = "Yes"
                else:
                    amount = line.credit
                    tally_amount = str(amount)
                    is_deemed_positive = "No"

                bill_allocations_xml = ""
                if line.partner_id:
                    bill_allocations_xml += f"""
                    <BILLALLOCATIONS.LIST>
                       <NAME>{entry.ref}</NAME>
                       <BILLTYPE>Agst Ref</BILLTYPE>
                       <AMOUNT>{tally_amount}</AMOUNT>
                   </BILLALLOCATIONS.LIST>
                """

                costcenter_xml = ""
                if line.analytic_distribution:
                    for analytic_id, percentage in line.analytic_distribution.items():
                        # FIX — convert analytic_id safely to int
                        try:
                            aid = int(analytic_id)
                        except Exception:
                            continue  # skip bad IDs

                        analytic = self.env['account.analytic.account'].browse(aid)
                        if not analytic:
                            continue

                        costcenter_xml += f"""
                                    <CATEGORYALLOCATIONS.LIST>
                                        <CATEGORY>{analytic.plan_id.name}</CATEGORY>
                                        <ISDEEMEDPOSITIVE>{is_deemed_positive}</ISDEEMEDPOSITIVE>
                                        <COSTCENTREALLOCATIONS.LIST>
                                            <NAME>{analytic.name}</NAME>
                                            <AMOUNT>{tally_amount}</AMOUNT>
                                        </COSTCENTREALLOCATIONS.LIST>
                                    </CATEGORYALLOCATIONS.LIST>
                                    """

                ledger_entries_xml_parts.append (f"""
                <ALLLEDGERENTRIES.LIST>
                    <LEDGERNAME>{line.account_id.name}</LEDGERNAME>
                    <ISDEEMEDPOSITIVE>{is_deemed_positive}</ISDEEMEDPOSITIVE>
                    <AMOUNT>{tally_amount}</AMOUNT>
                    {bill_allocations_xml}
                    {costcenter_xml}
                </ALLLEDGERENTRIES.LIST>
                """
                )

                voucher_type = "Journal"

        else:
            raise ValidationError(f"Tally XML generation not implemented for move type {move.move_type}")

        all_ledger_entries_xml = "\n".join(ledger_entries_xml_parts)

        # ==============================
        # Final XML Build
        # ==================================
        obj_view = "Accounting Voucher View"

        party = move.partner_id.name if move.partner_id else ""

        party_xml = ""
        if move.move_type in ['out_invoice', 'in_invoice'] and party:
            party_xml = f"""
                <PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>
                <PARTYNAME>{party}</PARTYNAME>
            """

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
                                     VCHTYPE="{voucher_type}"
                                     ACTION="{tally_action}"
                                     OBJVIEW="{obj_view}">
                                <DATE>{move_date_str}</DATE>
                                <REFERENCEDATE>{move_date_str}</REFERENCEDATE>
                                <GUID>{voucher_guid}</GUID>
                                <NARRATION>{narration}</NARRATION>
                                <VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>
                                <VOUCHERNUMBER>{move.name}</VOUCHERNUMBER>
                                <REFERENCE>{move.name}</REFERENCE>
                                <EFFECTIVEDATE>{move_date_str}</EFFECTIVEDATE>
                                <PERSISTEDVIEW>"{obj_view}"</PERSISTEDVIEW>
                                <ISINVOICE>{"Yes" if move.move_type in ['out_invoice', 'in_invoice'] else "No"}</ISINVOICE>
                                {party_xml}
                                {all_ledger_entries_xml}
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
        move = self
        voucher_guid = move.tally_guid
        tally_action = "Alter"

        # Check the move name BEFORE generating XML (it should have been set in _post)
        if not move.name or move.name == '/':
            # This should ideally not happen if _post is fixed, but it's a safety net
            return (False, f"Invoice number not yet assigned for Odoo move ID {move.id}.", None)

        if not voucher_guid:
            # We use the final assigned move.name to ensure the GUID is somewhat unique and traceable
            voucher_guid = str(move.id)
            tally_action = "Create"

        try:
            xml_data = self._generate_tally_xml(
                move=move,
                tally_action=tally_action,
                voucher_guid=voucher_guid
            )

            _logger.info(f"Tally XML for entry {move.name}:\n{xml_data}")

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
                success_message = _get_tally_success_message(move)
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
            message = f"An unexpected error occurred: {str(e)}"
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

    # def _post(self, soft=True):
    #     """
    #     Overridden _post method — posts normally first, then pushes to Tally afterward.
    #     Guarantees that move.name (invoice number) is already assigned.
    #     """
    #     # --- First, call Odoo's standard posting logic ---
    #     res = super()._post(soft=soft)
    #
    #     for move in self:
    #         # Skip Tally push for opening balance entries
    #         is_opening_balance_entry = (
    #                 move.move_type == 'entry'
    #                 and 'Tally Prime Opening Balances as of' in (move.ref or '')
    #         )
    #         if is_opening_balance_entry:
    #             _logger.info(
    #                 f"Skipping Tally push for Journal Entry {move.name}. "
    #                 f"Detected Tally Prime Opening Balances entry."
    #             )
    #             move.posted_to_tally = True
    #             continue
    #
    #         # Only push if not already pushed
    #         if not move.posted_to_tally:
    #             _logger.info(f"Pushing {move.name} to Tally after successful post.")
    #             success, message, new_guid = move._push_to_tally_core()
    #
    #             write_vals = {'tally_response': message}
    #             if success:
    #                 write_vals['posted_to_tally'] = True
    #                 if new_guid:
    #                     write_vals['tally_guid'] = new_guid
    #                 _logger.info(f"Tally push successful for {move.name}.")
    #             else:
    #                 _logger.error(f"Tally push failed for {move.name}: {message}")
    #
    #             move.write(write_vals)
    #
    #             # Optional: Notify the user if push failed (non-blocking)
    #             if not success:
    #                 move.message_post(
    #                     body=f"<b>Tally Push Failed:</b><br/>{message}",
    #                     subtype_xmlid="mail.mt_note",
    #                 )
    #
    #     return res

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        # after creation ensure mapping is applied for move lines
        for move in moves:
            move._apply_tally_account_mapping()
        return moves

    def _apply_tally_account_mapping(self):
        """Apply mapping for existing move lines. Debug-version: logs and messages changes."""
        for move in self:
            if move.move_type not in ('in_invoice', 'out_invoice'):
                continue

            _logger.info("TALLY-MAP: Applying mapping for move %s (id=%s)", move.name, move.id)
            debug_msgs = []

            # PRODUCT LINES
            for line in move.line_ids.filtered(lambda l: l.product_id and l.account_id):
                before_acc = line.account_id.name or False
                applied = False
                if move.move_type == 'in_invoice':
                    if move.partner_id and getattr(move.partner_id, 'tally_purchase_account_id', False):
                        line.write({'account_id': move.partner_id.tally_purchase_account_id.id})
                        applied = True
                        debug_msgs.append(
                            f"Product line {line.id}: used partner.tally_purchase_account_id -> {move.partner_id.tally_purchase_account_id.name}")
                    elif getattr(line.product_id, 'tally_purchase_ledger_id', False):
                        line.write({'account_id': line.product_id.tally_purchase_ledger_id.id})
                        applied = True
                        debug_msgs.append(
                            f"Product line {line.id}: used product.tally_purchase_ledger_id -> {line.product_id.tally_purchase_ledger_id.name}")
                else:  # out_invoice
                    if move.partner_id and getattr(move.partner_id, 'tally_sales_account_id', False):
                        line.write({'account_id': move.partner_id.tally_sales_account_id.id})
                        applied = True
                        debug_msgs.append(
                            f"Product line {line.id}: used partner.tally_sales_account_id -> {move.partner_id.tally_sales_account_id.name}")
                    elif getattr(line.product_id, 'tally_sales_ledger_id', False):
                        line.write({'account_id': line.product_id.tally_sales_ledger_id.id})
                        applied = True
                        debug_msgs.append(
                            f"Product line {line.id}: used product.tally_sales_ledger_id -> {line.product_id.tally_sales_ledger_id.name}")

                if not applied:
                    debug_msgs.append(
                        f"Product line {line.id}: no product/partner mapping; left account '{before_acc}'")

            # PAYABLE / RECEIVABLE LINES
            payable_lines = move.line_ids.filtered(
                lambda l: l.account_id and l.account_id.account_type == 'liability_payable'
            )
            receivable_lines = move.line_ids.filtered(
                lambda l: l.account_id and l.account_id.account_type == 'asset_receivable'
            )

            if getattr(move.partner_id, 'tally_payable_account_id', False):
                for pl in payable_lines:
                    before = pl.account_id.name
                    pl.write({'account_id': move.partner_id.tally_payable_account_id.id})
                    debug_msgs.append(
                        f"Payable line {pl.id}: replaced '{before}' -> '{move.partner_id.tally_payable_account_id.name}'")

            if getattr(move.partner_id, 'tally_receivable_account_id', False):
                for rl in receivable_lines:
                    before = rl.account_id.name
                    rl.write({'account_id': move.partner_id.tally_receivable_account_id.id})
                    debug_msgs.append(
                        f"Receivable line {rl.id}: replaced '{before}' -> '{move.partner_id.tally_receivable_account_id.name}'")

            # TAX LINES - robust detection for pre/post posting
            for tline in move.line_ids:
                # snapshot before
                before_acc = tline.account_id.name if tline.account_id else False
                dt = tline.display_type or ''
                tax_ids = [t.name for t in tline.tax_ids] if tline.tax_ids else []
                tax_line = getattr(tline, 'tax_line_id', False)
                tax_line_name = tax_line.name if tax_line else False

                # Try pre-post mapping: display_type == 'tax' and tax_ids
                if tline.display_type == 'tax' and tline.tax_ids:
                    tax = tline.tax_ids[0]
                    if getattr(tax, 'tally_tax_account_id', False):
                        tline.write({'account_id': tax.tally_tax_account_id.id})
                        debug_msgs.append(
                            f"Tax-line {tline.id} (pre-post): tax {tax.name} -> wrote account {tax.tally_tax_account_id.name}")
                        continue
                    else:
                        debug_msgs.append(
                            f"Tax-line {tline.id} (pre-post): tax {tax.name} has no tally mapping; left '{before_acc}'")

                # Try post mapping: tax_line_id set
                if tax_line:
                    tax = tax_line
                    if getattr(tax, 'tally_tax_account_id', False):
                        tline.write({'account_id': tax.tally_tax_account_id.id})
                        debug_msgs.append(
                            f"Tax-line {tline.id} (post): tax {tax.name} -> wrote account {tax.tally_tax_account_id.name}")
                    else:
                        debug_msgs.append(
                            f"Tax-line {tline.id} (post): tax {tax.name} has no tally mapping; left '{before_acc}'")

            # Push debug messages to log and chatter for quick inspection
            for m in debug_msgs:
                _logger.info("TALLY-MAP DEBUG: %s", m)

            # Add a compact message to the move chatter (limit length)
            short_msg = "<br/>".join(debug_msgs[:30])
            if short_msg:
                try:
                    move.message_post(body=f"<b>Tally mapping debug:</b><br/>{short_msg}", subtype_xmlid="mail.mt_note")
                except Exception:
                    _logger.exception("Failed to post debug message on move %s", move.id)

    def action_post(self):
        # --- Pre-mapping ---
        for move in self:
            try:
                move._recompute_dynamic_lines(recompute_all_taxes=True)
            except Exception:
                pass

            move._apply_tally_account_mapping()

        # --- Standard posting ---
        res = super().action_post()

        # after res = super().action_post()
        for move in self:
            for line in move.line_ids:
                # Pre-post tax rows: display_type == 'tax'
                if line.display_type == 'tax' and line.tax_ids:
                    tax = line.tax_ids[0]
                    if getattr(tax, 'tally_tax_account_id', False):
                        _logger.info("TALLY-FORCE: move %s line %s pre-post tax %s -> writing account %s", move.name,
                                     line.id, tax.name, tax.tally_tax_account_id.name)
                        try:
                            line.write({'account_id': tax.tally_tax_account_id.id})
                        except Exception:
                            _logger.exception("Failed to write tax account for line %s", line.id)

                # Post-post tax rows: tax_line_id
                if getattr(line, 'tax_line_id', False):
                    tax = line.tax_line_id
                    if getattr(tax, 'tally_tax_account_id', False):
                        _logger.info("TALLY-FORCE: move %s line %s post tax %s -> writing account %s", move.name,
                                     line.id, tax.name, tax.tally_tax_account_id.name)
                        try:
                            line.write({'account_id': tax.tally_tax_account_id.id})
                        except Exception:
                            _logger.exception("Failed to write tax account for line %s", line.id)

                # Payable/receivable ensure using account_type (Odoo 18)
                if line.account_id and line.account_id.account_type == 'liability_payable' and getattr(move.partner_id,
                                                                                                       'tally_payable_account_id',
                                                                                                       False):
                    try:
                        line.write({'account_id': move.partner_id.tally_payable_account_id.id})
                    except Exception:
                        _logger.exception("Failed to write payable account for line %s", line.id)
                if line.account_id and line.account_id.account_type == 'asset_receivable' and getattr(move.partner_id,
                                                                                                      'tally_receivable_account_id',
                                                                                                      False):
                    try:
                        line.write({'account_id': move.partner_id.tally_receivable_account_id.id})
                    except Exception:
                        _logger.exception("Failed to write receivable account for line %s", line.id)
            return res

    def _get_default_credit_account(self):
        self.ensure_one()
        partner = self.partner_id

        # If vendor has Tally Payable mapping, use it
        if partner.tally_payable_account_id:
            return partner.tally_payable_account_id

        # Otherwise fallback to Odoo default logic
        return super()._get_default_credit_account()

    def _recompute_dynamic_lines(self, recompute_all_taxes=False, **kwargs):
        """
        After Odoo computes tax lines, we replace their account with Tally mapped account.
        """
        res = super()._recompute_dynamic_lines(
            recompute_all_taxes=recompute_all_taxes, **kwargs
        )

        # After tax lines are computed, ensure tax lines use the mapped tally tax ledger
        for move in self:
            for line in move.line_ids.filtered(lambda l: l.tax_line_id):
                tax = line.tax_line_id
                if tax and getattr(tax, 'tally_tax_account_id', False):
                    line.account_id = tax.tally_tax_account_id

        return res

