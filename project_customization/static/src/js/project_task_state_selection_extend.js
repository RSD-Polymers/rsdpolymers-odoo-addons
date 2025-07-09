/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProjectTaskStateSelection } from "@project/components/project_task_state_selection/project_task_state_selection";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation"; // <--- ADD THIS IMPORT IF NOT ALREADY THERE AND USE DIRECTLY
import { formatSelection } from "@web/views/fields/formatters";

patch(ProjectTaskStateSelection.prototype, {
    setup() {
        super.setup();
        this.notification = useService("notification");
        this.action = useService("view");

        // Your custom icon/color definitions for '05_send_for_checking'
        this.icons['05_send_for_checking'] = "fa fa-lg fa-paper-plane";
        this.colorIcons['05_send_for_checking'] = "o_status_warning";
        this.colorButton['05_send_for_checking'] = "btn-outline-warning";

        // --- NEW ICONS/COLORS FOR '06_rejected' ---
        this.icons['06_rejected'] = "fa fa-lg fa-times-circle"; // A cross icon for rejected
        this.colorIcons['06_rejected'] = "text-danger";         // Red color
        this.colorButton['06_rejected'] = "btn-outline-danger"; // Red button style
        // --- END NEW ---
    },

    get label() {
        // Access the original selection directly from the field definition,
        // which contains all possible state values and their labels.
        const fullSelection = this.props.record.fields[this.props.name].selection;

        // Use formatSelection with the complete list to ensure the label is found.
        return formatSelection(this.currentValue, {
            selection: fullSelection,
        });
    },

    get options() {
        let originalOptions = super.options;

        const newState = ['05_send_for_checking', 'Send For Checking'];
        const approvedIndex = originalOptions.findIndex(option => option[0] === '03_approved');

        if (approvedIndex !== -1) {
            originalOptions.splice(approvedIndex + 1, 0, newState);
        } else {
            originalOptions.push(newState);
        }

        // --- ADD THE NEW '07_rejected' STATE TO THE OPTIONS ---
        // Find a suitable place to insert it. For now, let's just add it at the end
        // if it's not already there, or after '1_canceled'.
        const rejectedState = ['06_rejected', _t('Rejected')]; // Use _t for translatability
        const canceledIndex = originalOptions.findIndex(option => option[0] === '1_canceled');

        if (canceledIndex !== -1) {
            // Insert after '1_canceled'
            originalOptions.splice(canceledIndex + 1, 0, rejectedState);
        } else {
            // Otherwise, just add it to the end
            originalOptions.push(rejectedState);
        }
        // --- END ADDING '07_rejected' ---

        const isAssigneeUser = this.props.record.data.is_assignees_group_member;
        const isCheckerUser = this.props.record.data.is_checker_field;

        if (isAssigneeUser && !isCheckerUser) {
            const statesToHideForAssignee = ['1_done', '1_canceled', '03_approved', '06_rejected'];
            originalOptions = originalOptions.filter(option =>
                !statesToHideForAssignee.includes(option[0])
            );
        }

        return originalOptions;
    },

    async updateRecord(newValue) {
        console.log(`--- updateRecord called with: ${newValue} ---`);
        const oldState = this.props.record.data.state;

        try {
            // Attempt to update the record on the server
            // If a server-side ValidationError or UserError occurs, this line will throw an exception.
            const result = await super.updateRecord(newValue);

            // This block will only execute if the 'super.updateRecord' call was successful.
            if (newValue === '05_send_for_checking' && oldState !== '05_send_for_checking') {
                // Introduce a small delay and then force a record load to ensure data is fresh.
                // This might be redundant if the 'reload_views' is triggered on error, but good for success path.
                await browser.setTimeout(100);
                await this.props.record.load();

                const attemptsLeft = this.props.record.data.allowed_attempts;

                this.notification.add(
                    _t(`You have ${attemptsLeft} attempts remaining.`),
                    {
                        title: _t("Attempts Remaining"),
                        type: attemptsLeft > 0 ? "warning" : "danger",
                        sticky: false,
                    }
                );
            }
            return result; // Return the result if successful
        } catch (error) {
            console.error("Error during state update (caught in component patch):", error);
            console.log("Entering component's catch block. Reverting UI, reloading record, and re-throwing error for global handler.");

            // 1. Immediately revert the UI field's value to its old state.
            // This ensures the dropdown visually snaps back to the correct value.
            this.props.record.data.state = oldState;

            // 2. Load the record from the server to ensure all fields, especially
            // computed ones, are synchronized with the backend's true state.
            await this.props.record.load();

            // 3. Re-throw the error. This is crucial. Odoo's global error handler
            // will catch this error and display the standard Odoo pop-up dialog
            // (like the one in your screenshot) with the server's error message.
            // The record will already be reloaded and the UI reverted by this point.
            throw error;
        }
    },

    /**
     * Getter to determine if the field should be disabled for UI interaction due to approved or rejected.
     */
    get isDisabledState() {
        return this.currentValue === '03_approved' || this.currentValue === '06_rejected';
    },
});