# -*- coding: utf-8 -*-
{
    'name': 'Attendance OT & Absent Portal Approval',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Attendance',
    'summary': 'Expose employee attendance OT and absent/late hours to managers via Portal with contract synchronization',
    'description': """
Attendance OT & Absent Portal Approval
======================================
Exposes Attendance Overtime (OT) and Absent/Late hours calculated from biometric attendance records (`zkteco.attendance.record`).

Key Features:
-------------
1. **Periodic Attendance Approval Sheets**:
   - Aggregates daily attendance machine records by Employee over customizable periods (Daily, Weekly, Monthly).
   - Computes raw Overtime (OT) hours, late arrival minutes, and unexcused absent hours per daily line.

2. **Manager Approval Workflow**:
   - Managers can select acceptable OT hours and excuse or deduct absent/late hours.
   - 2-State approval: Draft/Submitted -> Approved / Rejected.

3. **Portal Exposure & Portal Self-Service**:
   - Integrates with `time_off_portal_exposure` to expose attendance approval cards on Portal Home (`/my`).
   - Portal Managers can review subordinate attendance reports, toggle acceptable OT per day, and approve/reject directly from the web portal interface.

4. **Active Employee Contract Synchronization**:
   - Upon manager approval, approved OT hours and absent/late hours automatically sync to the employee's active `hr.contract`.
   - Adds an **"Attendance & OT Summary"** tab on the Contract view with OT amounts and deduction summaries.
    """,
    'author': 'Custom Development',
    'website': 'https://www.odoo.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_contract',
        'hr_payroll',
        'portal',
        'zkteco_attendance',
        'time_off_portal_exposure',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/attendance_ot_sheet_views.xml',
        'views/hr_contract_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_employee_views.xml',
        'views/portal_templates.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'attendance_ot_portal_approval/static/src/css/attendance_ot_portal.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
