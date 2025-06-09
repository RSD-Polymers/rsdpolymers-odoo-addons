/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProjectTaskStateSelection } from "@project/components/project_task_state_selection/project_task_state_selection";
import { useState } from "@odoo/owl"; // Keep useState if you're using it for other local state

patch(ProjectTaskStateSelection.prototype, {
    setup() {
        super.setup();

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

        // Access the value of the computed field from the current record's data.
        // `this.props.record.data` contains all fields loaded for the current record.
        const isAssigneeUser = this.props.record.data.is_assignees_group_member;

        if (isAssigneeUser) {
            const statesToHideForAssignee = ['1_done', '1_canceled', '03_approved'];
            originalOptions = originalOptions.filter(option =>
                !statesToHideForAssignee.includes(option[0])
            );
        }

        return originalOptions;
    },
});