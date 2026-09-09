# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    ot_day_hours = fields.Float(
        string='Day OT (1.5x) Hours',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Approved Day Overtime (1.5x) hours in this payslip period. Available in Python salary rules as payslip.ot_day_hours',
    )
    ot_night_hours = fields.Float(
        string='Night OT (1.75x) Hours',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Approved Night Overtime (1.75x) hours in this payslip period. Available in Python salary rules as payslip.ot_night_hours',
    )
    ot_weekend_hours = fields.Float(
        string='Weekend OT (2.0x) Hours',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Approved Weekend Overtime (2.0x) hours in this payslip period. Available in Python salary rules as payslip.ot_weekend_hours',
    )
    ot_holiday_hours = fields.Float(
        string='Holiday OT (2.5x) Hours',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Approved Holiday Overtime (2.5x) hours in this payslip period. Available in Python salary rules as payslip.ot_holiday_hours',
    )
    approved_ot_hours = fields.Float(
        string='Total Approved OT Hours',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Total approved overtime hours in this payslip period. Available in Python salary rules as payslip.approved_ot_hours',
    )

    approved_absent_hours = fields.Float(
        string='Approved Absent / Late Deduction Hours',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Unapproved late arrival or absent hours to be deducted in this payslip period. Available in Python salary rules as payslip.approved_absent_hours',
    )
    approved_absent_days = fields.Integer(
        string='Approved Absent Deduction Days',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        help='Unapproved/deducted absent days approved by manager in this payslip period. Available in Python salary rules as payslip.approved_absent_days',
    )

    total_ot_amount = fields.Float(
        string='Total Overtime Payment (Birr)',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Total calculated overtime earnings for this payslip period. Available in Python salary rules as payslip.total_ot_amount',
    )
    absent_deduction_amount = fields.Float(
        string='Total Absent Deduction (Birr)',
        compute='_compute_attendance_ot_and_absent',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Total calculated absent deduction for this payslip period. Available in Python salary rules as payslip.absent_deduction_amount',
    )

    attendance_ot_sheet_ids = fields.Many2many(
        'attendance.ot.approval.sheet',
        string='Approved Attendance OT Sheets',
        compute='_compute_attendance_ot_sheet_ids',
        help='Approved attendance sheets corresponding to this payslip period.',
    )

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_attendance_ot_sheet_ids(self):
        for slip in self:
            if slip.employee_id and slip.date_from and slip.date_to:
                sheets = self.env['attendance.ot.approval.sheet'].search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', '=', 'approved'),
                    ('date_from', '<=', slip.date_to),
                    ('date_to', '>=', slip.date_from),
                ])
                slip.attendance_ot_sheet_ids = sheets
            else:
                slip.attendance_ot_sheet_ids = False

    @api.depends('employee_id', 'contract_id', 'date_from', 'date_to')
    def _compute_attendance_ot_and_absent(self):
        for slip in self:
            # Preserve already finalized payslip hours and amounts
            if slip.state in ('done', 'paid'):
                continue

            if not slip.employee_id or not slip.date_from or not slip.date_to:
                slip.ot_day_hours = 0.0
                slip.ot_night_hours = 0.0
                slip.ot_weekend_hours = 0.0
                slip.ot_holiday_hours = 0.0
                slip.approved_ot_hours = 0.0
                slip.approved_absent_hours = 0.0
                slip.approved_absent_days = 0
                slip.total_ot_amount = 0.0
                slip.absent_deduction_amount = 0.0
                continue

            # Search approved sheets matching payslip period
            sheets = self.env['attendance.ot.approval.sheet'].search([
                ('employee_id', '=', slip.employee_id.id),
                ('state', '=', 'approved'),
                ('date_from', '<=', slip.date_to),
                ('date_to', '>=', slip.date_from),
            ])

            contract = slip.contract_id
            if sheets:
                day_h = sum(sheets.mapped('total_ot_day_hours'))
                night_h = sum(sheets.mapped('total_ot_night_hours'))
                weekend_h = sum(sheets.mapped('total_ot_weekend_hours'))
                holiday_h = sum(sheets.mapped('total_ot_holiday_hours'))
                tot_ot = sum(sheets.mapped('total_approved_ot_hours'))
                absent_h = sum(sheets.mapped('total_approved_late_hours'))
                absent_d = sum(sheets.mapped('total_approved_absent_days'))
            elif contract:
                # Fallback to contract assigned values
                day_h = contract.ot_day_hours or 0.0
                night_h = contract.ot_night_hours or 0.0
                weekend_h = contract.ot_weekend_hours or 0.0
                holiday_h = contract.ot_holiday_hours or 0.0
                tot_ot = contract.approved_ot_hours or (day_h + night_h + weekend_h + holiday_h)
                absent_h = contract.approved_absent_hours or 0.0
                absent_d = contract.approved_absent_days or 0
            else:
                day_h = night_h = weekend_h = holiday_h = tot_ot = absent_h = 0.0
                absent_d = 0

            slip.ot_day_hours = day_h
            slip.ot_night_hours = night_h
            slip.ot_weekend_hours = weekend_h
            slip.ot_holiday_hours = holiday_h
            slip.approved_ot_hours = tot_ot
            slip.approved_absent_hours = absent_h
            slip.approved_absent_days = absent_d

            # Calculate amounts using 176 working hours standard
            work_hours = contract.monthly_working_hours or 176.0 if contract else 176.0
            base_rate = contract.base_hourly_rate or ((contract.wage or 0.0) / work_hours if contract else 0.0)
            day_rate = contract.ot_day_rate or (base_rate * 1.5)
            night_rate = contract.ot_night_rate or (base_rate * 1.75)
            weekend_rate = contract.ot_weekend_rate or (base_rate * 2.0)
            holiday_rate = contract.ot_holiday_rate or (base_rate * 2.5)
            absent_rate = contract.absent_hourly_rate or base_rate

            ot_amt = (day_h * day_rate) + (night_h * night_rate) + (weekend_h * weekend_rate) + (holiday_h * holiday_rate)
            ded_amt = absent_h * absent_rate

            slip.total_ot_amount = ot_amt
            slip.absent_deduction_amount = ded_amt

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self._reset_contract_ot_and_absent()
        return res

    def action_payslip_paid(self):
        res = super().action_payslip_paid()
        self._reset_contract_ot_and_absent()
        return res

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') in ('done', 'paid'):
            self._reset_contract_ot_and_absent()
        return res

    def _reset_contract_ot_and_absent(self):
        """Once salary is confirmed or paid, reset the contract's OT and absent hours/days to 0."""
        contracts = self.mapped('contract_id')
        if contracts:
            contracts.action_reset_ot_absent_hours()

    def action_payslip_draft(self):
        res = super().action_payslip_draft()
        # When moving back to draft, restore OT and absent values from approved sheets if present
        for slip in self:
            if slip.contract_id:
                sheets = self.env['attendance.ot.approval.sheet'].search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', '=', 'approved'),
                    ('date_from', '<=', slip.date_to),
                    ('date_to', '>=', slip.date_from),
                ], order='date_to desc', limit=1)
                if sheets:
                    sheets._sync_to_contract()
        return res

