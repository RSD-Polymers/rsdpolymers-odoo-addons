# models/res_config_settings.py

from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    essl_wsdl_url = fields.Char(
        string="eSSL WSDL URL",
        config_parameter='essl_attendance_sync.wsdl_url',
        default='http://etime.esslsecurity.com/WebAPIService.asmx?wsdl',
        help="The WSDL URL for the eSSL SOAP Web Service."
    )
    essl_user_name = fields.Char(
        string="eSSL Username",
        config_parameter='essl_attendance_sync.username',
        help="The UserName parameter for GetTransactionsLog."
    )
    essl_password = fields.Char(
        string="eSSL Password",
        config_parameter='essl_attendance_sync.password',
        help="The UserPassword parameter for GetTransactionsLog."
    )
    essl_serial_number = fields.Char(
        string="eSSL Serial Number",
        config_parameter='essl_attendance_sync.serial_number',
        help="The SerialNumber parameter (comma-separated if multiple)."
    )