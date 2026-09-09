from odoo import fields, models, api
import json, logging

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tally_company_name = fields.Char(
        string="Tally Company Name",
        default="Tally Test",
        help="The exact name of the company in Tally ERP/Prime."
    )
    tally_host = fields.Char(
        string="Tally Host",
        default="localhost",
        help="The IP address or hostname where Tally is running."
    )
    tally_port = fields.Integer(
        string="Tally Port",
        default=9000,  # Default Tally port for integration
        help="The port number Tally is listening on for API calls."
    )
    tally_xml_path = fields.Char(
        string="Tally XML Export Path",
        help="Local path to save generated Tally XML files before pushing (optional)."
    )

    # # Tally ODBC Connection Settings
    # tally_odbc_dsn = fields.Char(
    #     string="Tally ODBC DSN",
    #     config_parameter='odoo_tally_integration.tally_odbc_dsn',
    #     help="The Data Source Name (DSN) configured for TallyPrime ODBC. E.g., 'TallyODBC64'"
    # )
    # tally_odbc_driver = fields.Char(
    #     string="Tally ODBC Driver",
    #     config_parameter='odoo_tally_integration.tally_odbc_driver',
    #     default="{Tally ODBC Driver}",  # Common default for Tally
    #     help="The name of the Tally ODBC driver. E.g., '{Tally ODBC Driver}' or '{TallyPrime}'"
    # )
    # tally_odbc_port = fields.Char(
    #     string="Tally ODBC Port",
    #     config_parameter='odoo_tally_integration.tally_odbc_port',
    #     default="9000",  # Default Tally ODBC port
    #     help="The port on which TallyPrime's ODBC server is running (usually 9000 or 9001)."
    # )
    # tally_odbc_remote_host = fields.Char(
    #     string="Tally ODBC Remote Host/IP",
    #     config_parameter='odoo_tally_integration.tally_odbc_remote_host',
    #     help="The IP address or hostname of the remote server where TallyPrime is running. Leave blank for local Tally."
    # )
    # tally_odbc_connection_string = fields.Char(
    #     string="Tally ODBC Connection String",
    #     compute='_compute_tally_odbc_connection_string',
    #     readonly=True,
    #     help="Automatically generated ODBC connection string based on DSN/Driver and Port."
    # )

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        self.env['ir.config_parameter'].set_param('odoo_tally_integration.tally_company_name', self.tally_company_name)
        self.env['ir.config_parameter'].set_param('odoo_tally_integration.tally_host', self.tally_host)
        self.env['ir.config_parameter'].set_param('odoo_tally_integration.tally_port', self.tally_port)
        self.env['ir.config_parameter'].set_param('odoo_tally_integration.tally_xml_path', self.tally_xml_path)

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()

        res.update(
            tally_company_name=ICPSudo.get_param('odoo_tally_integration.tally_company_name'),
            tally_host=ICPSudo.get_param('odoo_tally_integration.tally_host'),
            tally_port=int(ICPSudo.get_param('odoo_tally_integration.tally_port') or 9000),
            tally_xml_path=ICPSudo.get_param('odoo_tally_integration.tally_xml_path'),
        )
        return res
