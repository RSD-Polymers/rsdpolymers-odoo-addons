/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

export class QaDashboard extends Component {
    static template = "qa_management.QaDashboard";

    setup() {
        // Static sample values for the initial dashboard layout.
        this.metrics = [
            { label: "Change Requests", value: "08", icon: "fa-refresh", color: "primary" },
            { label: "Complaints / NC", value: "05", icon: "fa-exclamation-circle", color: "danger" },
            { label: "Audits", value: "03", icon: "fa-clipboard-check", color: "success" },
            { label: "SOPs Under Review", value: "12", icon: "fa-file-text-o", color: "info" },
        ];
        this.quickLinks = [
            { title: "Change Management", description: "Change Control and Document Change Request", icon: "fa-exchange" },
            { title: "Complaints / Non-Compliance", description: "Customer Complaints and Product / Process Non-Conformity", icon: "fa-exclamation-triangle" },
            { title: "Audits", description: "Internal Audits, MRM and MOM, Trend Analysis", icon: "fa-clipboard" },
            { title: "Document Control (Revalidation)", description: "SOP, Forms and Formats, QSM", icon: "fa-folder-open" },
            { title: "KPA/KRA", description: "Quality team performance areas and key results", icon: "fa-users" },
        ];
        this.activities = [
            { title: "Change Control", detail: "Change Management • Sample dashboard activity", status: "In Progress", tone: "info", date: "Today" },
            { title: "Customer Complaint", detail: "Complaints / Non-Compliance • Sample activity", status: "Open", tone: "danger", date: "Today" },
            { title: "Internal Audit", detail: "Audits • Sample dashboard activity", status: "Scheduled", tone: "warning", date: "Yesterday" },
            { title: "SOP Review", detail: "Document Control • Sample dashboard activity", status: "Under Review", tone: "secondary", date: "Yesterday" },
        ];
    }
}

registry.category("actions").add("qa_management.dashboard", QaDashboard);
