/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProjectTaskStateSelection } from "@project/components/project_task_state_selection/project_task_state_selection";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation"; // <--- ADD THIS IMPORT IF NOT ALREADY THERE AND USE DIRECTLY

patch(ProjectTaskStateSelection.prototype, {
    setup() {
        super.setup();
        this.notification = useService("notification");

        // Your custom icon/color definitions for '05_send_for_checking'
        this.icons['05_send_for_checking'] = "fa fa-lg fa-paper-plane";
        this.colorIcons['05_send_for_checking'] = "o_status_warning";
        this.colorButton['05_send_for_checking'] = "btn-outline-warning";
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

        const isAssigneeUser = this.props.record.data.is_assignees_group_member;

        if (isAssigneeUser) {
            const statesToHideForAssignee = ['1_done', '1_canceled', '03_approved'];
            originalOptions = originalOptions.filter(option =>
                !statesToHideForAssignee.includes(option[0])
            );
        }

        return originalOptions;
    },

    async updateRecord(newValue) {
        console.log(`--- updateRecord called with: ${newValue} ---`);
        const oldState = this.props.record.data.state;

        const result = await super.updateRecord(newValue);

        if (newValue === '05_send_for_checking' && oldState !== '05_send_for_checking') {
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
        return result;
    },
});