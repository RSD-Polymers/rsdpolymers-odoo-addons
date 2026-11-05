# QA Inspection and Deviation Management – Odoo 18

## Included changes

- Adds a single **Inspection** menu under Quality Assurance.
- Adds MO Inspection, Planned Deviation, Post-Process Deviation and All Deviations under that menu.
- Automatically creates one `qa.manufacturing.inspection` when an MO is confirmed through `mrp.production.action_confirm()`.
- Prevents duplicate primary inspections per MO using a database uniqueness constraint.
- Adds multiple `qa.deviation` records per MO and per inspection.
- Supports Planned and Post-Process deviation types with investigation, corrective/preventive action, approval and closure fields.
- Adds a **Create Deviation** action on the MO Inspection form.
- Adds a QA Verified tag to the MO only after QA verification. No QA Pending or QA Rejected tags are created and no custom QA state is added to `mrp.production`.
- QA verification is restricted to a completed MO and requires confirmation that production records, chemist approval, QC results and sample testing were reviewed. All linked deviations must be Approved or Closed.
- Adds a revoke-verification action for QA Managers; revoking removes the QA Verified tag and records a chatter message.
- Preserves the existing Change Control workflow and menus.

## Important scope note

The current attached source package does not expose a confirmed relationship between the custom sample-testing records and `quality.check` records and an MO. Accordingly, this implementation provides QA review checklist fields and structured QC/sample-testing reference and result notes; it does **not** automatically fetch or validate all QC/sample-testing records. A follow-up integration should map the actual QC and sample-testing models used in the live database before enabling automatic completeness checks.

The QA Verified tag is an identification marker. This implementation does not itself validate stock transfers, change inventory locations, or implement a complete finished-goods release gate.

## Deployment

1. Back up the database and custom addons directory.
2. Copy the updated `rsd_qa_management` folder to the configured custom addons path, replacing the existing module folder only after comparing local changes.
3. Restart the Odoo service.
4. Upgrade the module, for example:

   ```bash
   ./odoo-bin -c /path/to/odoo.conf -d DATABASE_NAME -u rsd_qa_management --stop-after-init
   ```

5. Restart Odoo normally and test in a staging database before production use.

## Required UAT

- Confirm an MO and verify that exactly one MO Inspection is created.
- Confirm the inspection is not created for a cancelled MO.
- Complete an MO, review all QA checklist items and verify it; confirm only the QA Verified tag appears on the MO.
- Attempt verification before MO completion; it must be blocked.
- Create multiple Planned and Post-Process deviations against one MO and verify they appear in the inspection and respective menu filters.
- Attempt QA verification with an open/rejected deviation; it must be blocked.
- Approve/close deviations and verify the MO; confirm the QA Verified tag is applied.
- Revoke verification as QA Manager and confirm the tag is removed and chatter audit message is recorded.
- Regression-test the existing Change Control workflow and the existing production/QC customizations.
