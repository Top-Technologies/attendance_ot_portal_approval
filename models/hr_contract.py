# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError



class HrContract(models.Model):
    _inherit = 'hr.contract'

    # Overtime Hours per Category (Ethiopian Labor Law standard factors)
    ot_day_hours = fields.Float(
        string='Day Work Overtime (1.5x) Hours',
        digits=(16, 2),
        tracking=True,
        help='Approved overtime hours worked during standard day hours (1.5x rate).',
    )
    ot_night_hours = fields.Float(
        string='Night Work Overtime (1.75x) Hours',
        digits=(16, 2),
        tracking=True,
        help='Approved overtime hours worked during night shift hours (1.75x rate).',
    )
    ot_weekend_hours = fields.Float(
        string='Weekends Work Overtime (2.0x) Hours',
        digits=(16, 2),
        tracking=True,
        help='Approved overtime hours worked on weekly rest days/weekends (2.0x rate).',
    )
    ot_holiday_hours = fields.Float(
        string='Holiday Work Overtime (2.5x) Hours',
        digits=(16, 2),
        tracking=True,
        help='Approved overtime hours worked on public holidays (2.5x rate).',
    )

    approved_ot_hours = fields.Float(
        string='Total Approved OT Hours',
        compute='_compute_total_approved_ot_hours',
        store=True,
        digits=(16, 2),
        help='Sum of all approved overtime hours across all categories.',
    )

    approved_absent_hours = fields.Float(
        string='Approved Absent / Late Deduction Hours',
        digits=(16, 2),
        tracking=True,
        help='Unapproved late arrival or absent hours to be deducted.',
    )
    approved_absent_days = fields.Integer(
        string='Approved Absent Deduction Days',
        tracking=True,
        help='Unapproved/deducted absent days approved by manager.',
    )

    # Working Hours & Hourly Rates per Category
    monthly_working_hours = fields.Float(
        string='Monthly Working Hours',
        default=176.0,
        digits=(16, 2),
        tracking=True,
        help='Standard monthly working hours used to calculate hourly rates (Default: 176.0 hours).',
    )
    base_hourly_rate = fields.Float(
        string='Base Hourly Rate (Birr/hr)',
        compute='_compute_hourly_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Base hourly wage calculated as basic contract wage divided by monthly working hours (176.0 hrs).',
    )
    ot_day_rate = fields.Float(
        string='Day OT Rate (1.5x)',
        compute='_compute_hourly_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Hourly rate for Day Work Overtime (1.5 * Base Hourly Rate).',
    )
    ot_night_rate = fields.Float(
        string='Night OT Rate (1.75x)',
        compute='_compute_hourly_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Hourly rate for Night Work Overtime (1.75 * Base Hourly Rate).',
    )
    ot_weekend_rate = fields.Float(
        string='Weekend OT Rate (2.0x)',
        compute='_compute_hourly_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Hourly rate for Weekend Work Overtime (2.0 * Base Hourly Rate).',
    )
    ot_holiday_rate = fields.Float(
        string='Holiday OT Rate (2.5x)',
        compute='_compute_hourly_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Hourly rate for Holiday Work Overtime (2.5 * Base Hourly Rate).',
    )

    ot_hourly_rate = fields.Float(
        string='Default OT Hourly Rate (Birr/hr)',
        related='ot_day_rate',
        readonly=False,
    )
    absent_hourly_rate = fields.Float(
        string='Absent Deduction Rate (Birr/hr)',
        compute='_compute_hourly_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Hourly rate applied for absent/late hour deductions.',
    )

    # Calculated Amounts per Category
    total_ot_day_amount = fields.Float(
        string='Day OT Amount (Birr)',
        compute='_compute_ot_and_absent_amounts',
        store=True,
        digits=(16, 2),
    )
    total_ot_night_amount = fields.Float(
        string='Night OT Amount (Birr)',
        compute='_compute_ot_and_absent_amounts',
        store=True,
        digits=(16, 2),
    )
    total_ot_weekend_amount = fields.Float(
        string='Weekend OT Amount (Birr)',
        compute='_compute_ot_and_absent_amounts',
        store=True,
        digits=(16, 2),
    )
    total_ot_holiday_amount = fields.Float(
        string='Holiday OT Amount (Birr)',
        compute='_compute_ot_and_absent_amounts',
        store=True,
        digits=(16, 2),
    )

    total_ot_amount = fields.Float(
        string='Total Overtime Payment (Birr)',
        compute='_compute_ot_and_absent_amounts',
        store=True,
        digits=(16, 2),
        help='Calculated sum of all overtime amounts.',
    )
    absent_deduction_amount = fields.Float(
        string='Total Absent Deduction (Birr)',
        compute='_compute_ot_and_absent_amounts',
        store=True,
        digits=(16, 2),
        help='Calculated as Approved Absent Hours * Absent Hourly Rate.',
    )

    attendance_ot_sheet_ids = fields.One2many(
        'attendance.ot.approval.sheet',
        'contract_id',
        string='Approved Attendance & OT Sheets',
    )
    approved_sheet_count = fields.Integer(
        string='Attendance Sheets Count',
        compute='_compute_approved_sheet_count',
    )

    @api.depends('ot_day_hours', 'ot_night_hours', 'ot_weekend_hours', 'ot_holiday_hours')
    def _compute_total_approved_ot_hours(self):
        for contract in self:
            contract.approved_ot_hours = (
                (contract.ot_day_hours or 0.0) +
                (contract.ot_night_hours or 0.0) +
                (contract.ot_weekend_hours or 0.0) +
                (contract.ot_holiday_hours or 0.0)
            )

    @api.depends('wage', 'monthly_working_hours')
    def _compute_hourly_rates(self):
        for contract in self:
            base = contract.wage or 0.0
            work_hours = contract.monthly_working_hours or 176.0
            hourly = (base / work_hours) if (base > 0 and work_hours > 0) else 0.0
            contract.base_hourly_rate = hourly
            contract.ot_day_rate = hourly * 1.5
            contract.ot_night_rate = hourly * 1.75
            contract.ot_weekend_rate = hourly * 2.0
            contract.ot_holiday_rate = hourly * 2.5
            contract.absent_hourly_rate = hourly

    @api.depends(
        'ot_day_hours', 'ot_day_rate',
        'ot_night_hours', 'ot_night_rate',
        'ot_weekend_hours', 'ot_weekend_rate',
        'ot_holiday_hours', 'ot_holiday_rate',
        'approved_absent_hours', 'absent_hourly_rate'
    )
    def _compute_ot_and_absent_amounts(self):
        for contract in self:
            day_amt = (contract.ot_day_hours or 0.0) * (contract.ot_day_rate or 0.0)
            night_amt = (contract.ot_night_hours or 0.0) * (contract.ot_night_rate or 0.0)
            weekend_amt = (contract.ot_weekend_hours or 0.0) * (contract.ot_weekend_rate or 0.0)
            holiday_amt = (contract.ot_holiday_hours or 0.0) * (contract.ot_holiday_rate or 0.0)

            contract.total_ot_day_amount = day_amt
            contract.total_ot_night_amount = night_amt
            contract.total_ot_weekend_amount = weekend_amt
            contract.total_ot_holiday_amount = holiday_amt
            contract.total_ot_amount = day_amt + night_amt + weekend_amt + holiday_amt

            contract.absent_deduction_amount = (contract.approved_absent_hours or 0.0) * (contract.absent_hourly_rate or 0.0)

    @api.depends('attendance_ot_sheet_ids')
    def _compute_approved_sheet_count(self):
        for contract in self:
            contract.approved_sheet_count = len(contract.attendance_ot_sheet_ids)

    def action_view_attendance_ot_sheets(self):
        self.ensure_one()
        return {
            'name': _('Attendance OT & Absent Sheets: %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'attendance.ot.approval.sheet',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_employee_id': self.employee_id.id, 'default_contract_id': self.id},
        }

    def action_reset_ot_absent_hours(self):
        """Reset temporary monthly OT and absent hours/days back to 0 once salary is paid or settled."""
        return self.write({
            'ot_day_hours': 0.0,
            'ot_night_hours': 0.0,
            'ot_weekend_hours': 0.0,
            'ot_holiday_hours': 0.0,
            'approved_absent_hours': 0.0,
            'approved_absent_days': 0,
        })

    def write(self, vals):
        if 'monthly_working_hours' in vals:
            if not self.env.user.has_group('base.group_system') and not self.env.is_superuser():
                raise AccessError(_("Only System Administrators can modify the Monthly Working Hours on employee contracts."))
        return super().write(vals)


