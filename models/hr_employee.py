# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    attendance_ot_sheet_ids = fields.One2many(
        'attendance.ot.approval.sheet',
        'employee_id',
        string='Attendance OT & Absent Sheets',
    )
    attendance_ot_sheet_count = fields.Integer(
        string='OT & Attendance Sheets Count',
        compute='_compute_attendance_ot_sheet_count',
    )

    is_portal_attendance_manager = fields.Boolean(
        string="Is Portal Attendance & OT Manager",
        help="Check this box to grant this employee portal manager privileges to review and approve team OT & attendance reports.",
    )

    @api.depends('attendance_ot_sheet_ids')
    def _compute_attendance_ot_sheet_count(self):
        for emp in self:
            emp.attendance_ot_sheet_count = len(emp.attendance_ot_sheet_ids)

    def action_view_attendance_ot_sheets(self):
        self.ensure_one()
        return {
            'name': _('Attendance OT & Absent Sheets: %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'attendance.ot.approval.sheet',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
